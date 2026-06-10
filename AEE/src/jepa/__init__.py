"""JEPA 世界模型子包 — I-JEPA（长期）+ V-JEPA（短时总结）"""

from .jepa_encoder import JepaEncoder, get_encoder, INPUT_DIM, LATENT_DIM, JEPA_STATE_DIMS
from .i_jepa import IJepa, get_i_jepa
from .v_jepa import VJepa, get_v_jepa

__all__ = [
    "JepaEncoder",
    "get_encoder",
    "INPUT_DIM",
    "LATENT_DIM",
    "JEPA_STATE_DIMS",
    "IJepa",
    "get_i_jepa",
    "VJepa",
    "get_v_jepa",
]
