# Copyright (c) 2022-2024, NVIDIA CORPORATION.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import warnings

from typing import Sequence, Optional, Union, List, Tuple, Iterator

from cugraph.gnn import UniformNeighborSampler, DistSampleWriter
from cugraph.utilities.utils import import_optional


import cugraph_dgl
from cugraph_dgl.nn import SparseGraph
from cugraph_dgl.typing import TensorType
from cugraph_dgl.dataloading.sampler import HomogeneousSampleReader

torch = import_optional("torch")


class NeighborSampler:
    """Sampler that builds computational dependency of node representations via
    neighbor sampling for multilayer GNN.
    This sampler will make every node gather messages from a fixed number of neighbors
    per edge type.  The neighbors are picked uniformly.
    Parameters
    ----------
    fanouts_per_layer : int
        List of neighbors to sample for each GNN layer, with the i-th
        element being the fanout for the i-th GNN layer.
        If -1 is provided then all inbound/outbound edges
        of that edge type will be included.
    edge_dir : str, default ``'in'``
        Can be either ``'in' `` where the neighbors will be sampled according to
        incoming edges, or ``'out'`` for outgoing edges
    replace : bool, default False
        Whether to sample with replacement
    Examples
    --------
    **Node classification**
    To train a 3-layer GNN for node classification on a set of nodes ``train_nid`` on
    a homogeneous graph where each node takes messages from 5, 10, 15 neighbors for
    the first, second, and third layer respectively (assuming the backend is PyTorch):
    >>> sampler = cugraph_dgl.dataloading.NeighborSampler([5, 10, 15])
    >>> dataloader = cugraph_dgl.dataloading.DataLoader(
    ...     g, train_nid, sampler,
    ...     batch_size=1024, shuffle=True)
    >>> for input_nodes, output_nodes, blocks in dataloader:
    ...     train_on(blocks)
    """

    def __init__(
        self,
        fanouts_per_layer: Sequence[int],
        edge_dir: str = "in",
        replace: bool = False,
        prob: Optional[str] = None,
        mask: Optional[str] = None,
        prefetch_node_feats: Optional[Union[List[str], dict[str, List[str]]]] = None,
        prefetch_edge_feats: Optional[
            Union[List[str], dict[Tuple[str, str, str], List[str]]]
        ] = None,
        prefetch_labels: Optional[Union[List[str], dict[str, List[str]]]] = None,
        output_device: Optional[Union["torch.device", int, str]] = None,
        fused: bool = True,
        **kwargs,
    ):
        """
        Parameters
        ----------
        fanouts_per_layer: Sequence[int]
            The number of neighbors to sample per layer.
        edge_dir: str
            Optional (default='in').
            The direction to traverse edges.
        replace: bool
            Optional (default=False).
            Whether to sample with replacement.
        prob: str
            Optional.
            If provided, the probability of each neighbor being
            sampled is proportional to the edge feature
            with the given name.  Mutually exclusive with mask.
            Currently unsupported.
        mask: str
            Optional.
            If proivided, only neighbors where the edge mask
            with the given name is True can be selected.
            Mutually exclusive with prob.
            Currently unsupported.
        prefetch_node_feats: Union[List[str], dict[str, List[str]]]
            Optional.
            Currently ignored by cuGraph-DGL.
        prefetch_edge_feats: Union[List[str], dict[Tuple[str, str, str], List[str]]]
            Optional.
            Currently ignored by cuGraph-DGL.
        prefetch_labels: Union[List[str], dict[str, List[str]]]
            Optional.
            Currently ignored by cuGraph-DGL.
        output_device: Union[torch.device, int, str]
            Optional.
            Output device for samples. Defaults to the current device.
        fused: bool
            Optional (default=True).
            This argument is ignored by cuGraph-DGL.
        **kwargs
            Keyword arguments for the underlying cuGraph distributed sampler
            and writer (directory, batches_per_partition, format,
            local_seeds_per_call).
        """

        if mask:
            raise NotImplementedError(
                "Edge masking is currently unsupported by cuGraph-DGL"
            )
        if prob:
            raise NotImplementedError(
                "Edge masking is currently unsupported by cuGraph-DGL"
            )
        if prefetch_edge_feats:
            warnings.warn("'prefetch_edge_feats' is ignored by cuGraph-DGL")
        if prefetch_node_feats:
            warnings.warn("'prefetch_node_feats' is ignored by cuGraph-DGL")
        if prefetch_labels:
            warnings.warn("'prefetch_labels' is ignored by cuGraph-DGL")
        if fused:
            warnings.warn("'fused' is ignored by cuGraph-DGL")

        self.fanouts = fanouts_per_layer
        reverse_fanouts = fanouts_per_layer.copy()
        reverse_fanouts.reverse()
        self._reversed_fanout_vals = reverse_fanouts

        self.edge_dir = edge_dir
        self.replace = replace
        self.__kwargs = kwargs

    def sample(
        self, g: "cugraph_dgl.Graph", indices: TensorType, batch_size: int = 1
    ) -> Iterator[Tuple["torch.Tensor", "torch.Tensor", List[SparseGraph]]]:
        kwargs = dict(**self.__kwargs)

        writer = DistSampleWriter(
            direction=kwargs.pop("directory", None),
            batches_per_partition=kwargs.pop("batches_per_partition", 256),
            format=kwargs.pop("format", "parquet"),
        )

        ds = UniformNeighborSampler(
            g._graph(self.edge_dir),
            writer,
            compression="CSC",
            fanout=self._reversed_fanout_vals,
            prior_sources_behavior="carryover",
            deduplicate_sources=True,
            compress_per_hop=True,
            with_replacement=self.replace,
            **kwargs,
        )

        if g.is_homogeneous:
            ds.sample_from_nodes(indices, batch_size=batch_size)
            return HomogeneousSampleReader(ds.get_reader())

        raise ValueError(
            "Sampling heterogeneous graphs is currently"
            " unsupported in the non-dask API"
        )
