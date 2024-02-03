import os
import json
from enum import Enum


def read_file(path):
    return open(os.path.join(os.path.dirname(__file__), path), 'r', encoding='utf-8')


FAUCET_RECAPTCHA_SITE_KEY = '6LfOA04pAAAAAL9ttkwIz40hC63_7IsaU2MgcwVH'

SCAN = 'https://artio.beratrail.io'

ZERO_ADDRESS = '0x0000000000000000000000000000000000000000'

W_BERA = '0x5806E416dA447b267cEA759358cF22Cc41FAE80F'
STG_USDC = '0x6581e59A1C8dA66eD0D313a0d4029DcE2F746Cc5'

BEX_W_BERA_STG_USDC_POOL = '0x7D5b5C1937ff1b18B45AbC64aeAB68663a7a58Ab'

BEX_ADDRESS = '0x0d5862FDbdd12490f9b4De54c236cff63B038074'
BEX_ABI = json.load(read_file('abi/bex.json'))

HONEY_ADDRESS = '0x09ec711b81cD27A6466EC40960F2f8D85BB129D9'
HONEY_ABI = json.load(read_file('abi/honey.json'))

ERC20_ABI = json.load(read_file('abi/erc20.json'))


class SwapKind(Enum):
    GIVEN_IN = 0
    GIVEN_OUT = 1
