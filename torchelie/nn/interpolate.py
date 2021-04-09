import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import List, Optional, Tuple, Union

class Interpolate2d(nn.Module):
    def __init__(self,
                 mode: str,
                 size: Optional[List[str]] = None,
                 scale_factor: Optional[float] = None) -> None:
        super().__init__()
        self.size = size
        self.scale_factor = scale_factor
        self.mode = mode

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        rsf = True if self.scale_factor is not None else None
        return F.interpolate(x,
                             mode=self.mode,
                             size=self.size,
                             scale_factor=self.scale_factor,
                             recompute_scale_factor=rsf,
                             align_corners=False)


    def extra_repr(self)->str:
        return f'scale_factor={self.scale_factor} size={self.size}'

class InterpolateBilinear2d(Interpolate2d):
    def __init__(
        self,
        size: Optional[List[str]] = None,
        scale_factor: Optional[float] = None,
    ) -> None:
        super().__init__(size=size, scale_factor=scale_factor, mode='bilinear')

