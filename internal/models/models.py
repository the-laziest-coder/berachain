from typing import Tuple, Optional
from dataclasses import dataclass, field
from dataclasses_json import dataclass_json
from eth_account import Account as EvmAccount
from eth_account.messages import encode_defunct


STATUS_BY_BOOL = {
    False: '❌',
    True: '✅',
}


@dataclass_json
@dataclass
class AccountInfo:
    idx: int = 0
    evm_address: str = ''
    evm_private_key: str = ''
    proxy: str = ''
    twitter_auth_token: str = ''
    email_username: str = ''
    email_password: str = ''
    twitter_error: bool = False
    points: dict[str, Tuple[str, int, Optional[bool]]] = field(default_factory=dict)
    drip_bera: bool = False
    swap_bera: bool = False
    mint_honey: bool = False

    def sign_message(self, msg):
        return EvmAccount().sign_message(encode_defunct(text=msg), self.evm_private_key).signature.hex()

    def str_stats(self) -> str:
        stats = {n: self.campaign_points_str(c_id) for c_id, (n, _, _) in self.points.items()}
        stats.update({
            'Drip $BERA ': STATUS_BY_BOOL[self.drip_bera],
            'Swap $BERA ': STATUS_BY_BOOL[self.swap_bera],
            'Mint $HONEY': STATUS_BY_BOOL[self.mint_honey],
        })
        return ''.join([f'\t{name}: {value}\n' for name, value in stats.items()])[:-1]

    def campaign_points_str(self, campaign_id) -> str:
        points = self.points.get(campaign_id)
        if not points:
            return '0'
        s = str(points[1])
        if points[2] is not None:
            s += ' / ' + STATUS_BY_BOOL[points[2]]
        return s

    @property
    def drip_bera_s(self):
        return STATUS_BY_BOOL[self.drip_bera]

    @property
    def swap_bera_s(self):
        return STATUS_BY_BOOL[self.swap_bera]

    @property
    def mint_honey_s(self):
        return STATUS_BY_BOOL[self.mint_honey]

    @property
    def twitter_error_s(self):
        return '🔴' if self.twitter_error else ''
