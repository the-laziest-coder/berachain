import time
import random
import asyncio
from loguru import logger
from termcolor import colored
from web3.exceptions import TransactionNotFound
from web3.contract.async_contract import AsyncContractConstructor

from ..models import AccountInfo
from ..captcha import solve_cloudflare_challenge
from ..tls import TLSClient
from ..utils import async_retry, get_proxy_url, get_w3, int_to_decimal, decimal_to_int
from ..config import WAIT_TX_TIME, WAIT_DRIP_TOKENS

from .constants import FAUCET_CLOUDFLARE_SITE_KEY, \
    ZERO_ADDRESS, W_BERA, STG_USDC, BEX_W_BERA_STG_USDC_POOL, \
    BEX_ADDRESS, BEX_ABI, HONEY_ADDRESS, HONEY_ABI, ERC20_ABI, \
    SCAN, SwapKind


class OnchainAccount:

    def __init__(self, idx, account: AccountInfo, private_key: str):
        self.idx = idx
        self.account = account
        self.private_key = private_key
        self.proxy = get_proxy_url(self.account.proxy)
        self.w3 = get_w3(self.proxy)
        self.tls = TLSClient(account, {
            'authority': 'artio-80085-ts-faucet-api-2.berachain.com',
            'content-type': 'text/plain;charset=UTF-8',
            'origin': 'https://artio.faucet.berachain.com',
            'cache-control': 'no-cache',
            'pragma': 'no-cache',
            'referer': 'https://artio.faucet.berachain.com/',
        })

    async def close(self):
        await self.tls.close()

    async def __aenter__(self) -> "OnchainAccount":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    @async_retry
    async def drip_bera(self, wait_drip_tokens=WAIT_DRIP_TOKENS):
        if int(time.time()) < self.account.last_drip_ts + 1200:
            logger.info(f'{self.idx}) The last drip was less than 20 minutes ago. Will not request more now')
            return
        try:
            captcha = await solve_cloudflare_challenge(
                self.idx,
                'https://artio.faucet.berachain.com',
                FAUCET_CLOUDFLARE_SITE_KEY,
                self.proxy,
            )

            def _handler(r):
                if 'Txhash' not in r['msg']:
                    raise Exception()
                return r['msg']

            msg = await self.tls.post(
                f'https://artio-80085-faucet-api-cf.berachain.com/api/claim?address={self.account.evm_address}',
                [200], _handler,
                headers={'Authorization': 'Bearer ' + captcha},
                data=f'{{"address":"{self.account.evm_address}"}}',
            )

            logger.success(f'{self.idx}) Drip $BERA done: {msg}')
            self.account.drip_bera = True
            self.account.last_drip_ts = int(time.time())

            if wait_drip_tokens:
                logger.info(f'{self.idx}) Waiting {WAIT_TX_TIME}s for tokens')
                for _ in range(0, WAIT_TX_TIME, 20):
                    await asyncio.sleep(20)
                    balance = await self.w3.eth.get_balance(self.account.evm_address)
                    if balance > 0:
                        logger.success(f'{self.idx}) Tokens received')
                        return
                    logger.info(f'{self.idx}) Still zero tokens')
                logger.info(f'{self.idx}) Finished waiting for tokens')

        except Exception as e:
            raise Exception(f'Failed to drip $BERA: {str(e)}')

    @async_retry
    async def _build_and_send_tx(self, func: AsyncContractConstructor, **tx_vars):
        max_priority_fee = await self.w3.eth.max_priority_fee
        max_priority_fee = int(max_priority_fee * 2)
        base_fee_per_gas = int((await self.w3.eth.get_block("latest"))["baseFeePerGas"])
        max_fee_per_gas = max_priority_fee + int(base_fee_per_gas * 2)
        tx = await func.build_transaction({
            'from': self.account.evm_address,
            'nonce': await self.w3.eth.get_transaction_count(self.account.evm_address),
            'maxPriorityFeePerGas': max_priority_fee,
            'maxFeePerGas': max_fee_per_gas,
            'gas': 0,
            **tx_vars,
        })
        try:
            estimate = await self.w3.eth.estimate_gas(tx)
            tx['gas'] = int(estimate * 1.2)
        except Exception as e:
            raise Exception(f'Tx simulation failed: {str(e)}')

        signed_tx = self.w3.eth.account.sign_transaction(tx, self.private_key)
        tx_hash = await self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)

        return tx_hash

    async def _tx_verification(self, tx_hash, action, poll_latency=1):
        logger.info(f'{self.idx}) {action} - Tx sent. Waiting for {WAIT_TX_TIME}s')
        time_passed = 0
        tx_link = f'{SCAN}/tx/{tx_hash.hex()}'
        while time_passed < WAIT_TX_TIME:
            try:
                tx_data = await self.w3.eth.get_transaction_receipt(tx_hash)
                if tx_data is not None:
                    if tx_data.get('status') == 1:
                        logger.success(f'{self.idx}) {action} - Successful tx: {tx_link}')
                        return
                    msg = f'Failed tx: {tx_link}'
                    logger.error(f'{self.idx}) {msg}')
                    raise Exception(msg)
            except TransactionNotFound:
                pass

            time_passed += poll_latency
            await asyncio.sleep(poll_latency)

        msg = f'{action} - Pending tx: {tx_link}'
        logger.warning(f'{self.idx}) {msg}')
        raise Exception(msg)

    async def build_and_send_tx(self, func: AsyncContractConstructor, action='', **tx_vars):
        tx_hash = await self._build_and_send_tx(func, **tx_vars)
        await self._tx_verification(tx_hash, action)

    async def approve_if_needed(self, token_address, spender, amount):
        contract = self.w3.eth.contract(token_address, abi=ERC20_ABI)
        if await contract.functions.allowance(self.account.evm_address, spender).call() < amount:
            await self.build_and_send_tx(contract.functions.approve(spender, 2 ** 256 - 1), 'Approve')

    @async_retry
    async def _swap_bera(self):
        balance = await self.w3.eth.get_balance(self.account.evm_address)
        if balance < 10 ** 16:
            logger.info(f'{self.idx}) Not enough $BERA balance. Trying to drip')
            await self.drip_bera(wait_drip_tokens=True)
        balance = await self.w3.eth.get_balance(self.account.evm_address)
        if balance < 10 ** 16:
            raise Exception(f'Not enough $BERA balance: {"%.5f" % int_to_decimal(balance, 18)}')

        amount = round(int_to_decimal(balance, 18) * random.uniform(0.1, 0.4), random.randint(3, 4))

        logger.info(f'{self.idx}) Swapping {amount} $BERA to stgUSDC')

        amount = decimal_to_int(amount, 18)

        resp = await self.tls.get(f'https://artio-80085-dex-router.berachain.com/dex/route'
                                  f'?quoteAsset={STG_USDC}'
                                  f'&baseAsset={W_BERA}'
                                  f'&amount={amount}'
                                  f'&swap_type=given_in',
                                  [200],
                                  headers={
                                      'origin': 'https://artio.bex.berachain.com',
                                      'referrer': 'https://artio.bex.berachain.com/'
                                  })

        amount_out = int(int(resp['steps'][-1]['amountOut']) * 0.9)
        route = [(BEX_W_BERA_STG_USDC_POOL, ZERO_ADDRESS, amount, STG_USDC, amount_out, b'')]
        deadline = 99999999
        args = (SwapKind.GIVEN_IN.value, route, deadline)

        contract = self.w3.eth.contract(BEX_ADDRESS, abi=BEX_ABI)

        await self.build_and_send_tx(contract.functions.batchSwap(*args), 'Swap $BERA', value=amount)

        logger.success(f'{self.idx}) Swap $BERA done')
        self.account.swap_bera = True

    async def swap_bera(self):
        try:
            logger.info(f'{self.idx}) Starting swap $BERA')
            await self._swap_bera()
        except Exception as e:
            raise Exception(f'Failed to swap $BERA: {str(e)}')

    @async_retry
    async def _mint_honey(self):
        stg_usdc = self.w3.eth.contract(STG_USDC, abi=ERC20_ABI)
        stg_usdc_balance = await stg_usdc.functions.balanceOf(self.account.evm_address).call()
        if stg_usdc_balance == 0:
            logger.info(f'{self.idx}) ' + colored('0 $stgUSDC in wallet. Starting swap', 'cyan'))
            await self.swap_bera()
            stg_usdc_balance = await stg_usdc.functions.balanceOf(self.account.evm_address).call()

        stg_usdc_amount = round(
            int_to_decimal(stg_usdc_balance, 18) * random.uniform(0.1, 0.9),
            random.randint(0, 2)
        )

        logger.info(f'{self.idx}) Minting $HONEY for {stg_usdc_amount} $stgUSDC')

        stg_usdc_amount = decimal_to_int(stg_usdc_amount, 18)

        honey = self.w3.eth.contract(HONEY_ADDRESS, abi=HONEY_ABI)

        await self.approve_if_needed(STG_USDC, HONEY_ADDRESS, stg_usdc_amount)

        args = self.account.evm_address, STG_USDC, stg_usdc_amount
        await self.build_and_send_tx(honey.functions.mint(*args), 'Mint $HONEY')

        logger.success(f'{self.idx}) Mint $HONEY done')
        self.account.mint_honey = True

    async def mint_honey(self):
        try:
            logger.info(f'{self.idx}) Starting mint $HONEY')
            await self._mint_honey()
        except Exception as e:
            raise Exception(f'Failed to mint HONEY: {str(e)}')
