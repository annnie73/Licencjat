from .common import OHEncoder
from torch.utils.data import Dataset
import torch
import os
from .exceptions import *
from warnings import warn
from rewrite_fasta import rewrite_fasta
import math


class SeqsDataset(Dataset):

    def __init__(self, data, subset=(), filetype='fasta', seq_len=2000, packedtype='fa', name_pos=None):

        # Establishing files' IDs and their directories
        if isinstance(data, str):
            if data.endswith((filetype, packedtype)):
                i, path = rewrite_fasta(data, name_pos=name_pos)
                if i == 1:
                    warn('Only one sequence found in the given data!')
                data = [path]
            elif os.path.isdir(data):
                data = [data]
            else:
                raise GivenDataError(data, filetype)
        elif isinstance(data, list) and any([el.endswith((filetype, packedtype)) for el in data]):
            for file in [el for el in data if el.endswith((filetype, packedtype))]:
                _, path = rewrite_fasta(file, name_pos=name_pos)
                data[data.index(file)] = path
        else:
            fs = [la for la in [os.path.join(dd, el) for dd in data for el in os.listdir(dd)] if la.endswith(packedtype)]
            if fs:
                new_data = []
                old_data = set()
                for file in fs:
                    old, _ = os.path.split(file)
                    old_data.add(old)
                    dd, _ = os.path.splitext(file)
                    if not os.path.isdir(dd):
                        i, path = rewrite_fasta(file, name_pos=name_pos)
                        if i == 1:
                            warn('Only one sequence found in the given data!')
                        new_data.append(path)
                    else:
                        new_data.append(dd)
                data.extend(new_data)
                for el in old_data:
                    data.remove(el)
        ids = []
        dirs = []
        locs = {}  # seq-name : index of element in dirs from which it was obtained
        for dd in data:
            if os.path.isfile(dd) and dd.endswith(filetype):
                name, _ = os.path.splitext(dd)
                if not subset or name in subset:
                    ids.append(name)
                    d = '/'.join(dd.split('/')[:-1])
                    dirs.append(d)
                    if name not in locs:
                        locs[name] = dirs.index(d)
                    else:
                        RepeatedFileError(name, dirs[locs[name]], d)
            for r, _, f in os.walk(dd, followlinks=True):
                fs = [el for el in f if el.endswith(filetype)]
                if len(fs) > 0:
                    if r not in dirs:
                        dirs.append(r)
                for file in fs:
                    name, _ = os.path.splitext(file)
                    if subset and name not in subset:
                        continue
                    ids.append(name)
                    if name not in locs:
                        locs[name] = dirs.index(r)
                    else:
                        raise RepeatedFileError(name, dirs[locs[name]], r)
        if len(ids) == 0:
            warn('No files of {} type was found in the given data'.format(filetype), UserWarning)
        self.IDs = ids
        self.locs = locs
        self.dirs = dirs
        self.filetype = filetype
        self.classes = ['promoter active', 'nonpromoter active', 'promoter inactive', 'nonpromoter inactive']
        self.num_classes = len(self.classes)
        self.num_seqs = len(self.IDs)
        self.seq_len = seq_len
        self.encoder = OHEncoder()
        self.to_remove = []

    def __len__(self):
        return len(self.IDs)

    def __getitem__(self, index, info=False):
        try:
            ID = self.IDs[int(index)]
        except ValueError:
            ID = index
        filename = os.path.join(self.dirs[self.locs[ID]], '{}.{}'.format(ID, self.filetype))
        with open(filename, 'r') as file:
            for line in file:
                if line.startswith('>'):
                    header = line.strip('\n> ').split(' ')
                    ch, midpoint, strand, t1, t2 = header[:5]
                    if len(header) > 5:
                        desc = ' '.join(header[5:])
                    else:
                        desc = None
                    label = self.classes.index('{} {}'.format(t1, t2))
                elif line:
                    seq = line.strip().upper()
                    if len(seq) > self.seq_len:
                        seq = seq[len(seq) // 2 - math.ceil(self.seq_len / 2): len(seq) // 2 + math.floor(self.seq_len / 2)]
                    else:
                        assert len(seq) == self.seq_len, 'Sequence {}: length {}'.format(self.IDs[index], len(seq))
                    break
            if file.readline().strip():
                warn('In file {} is more than one sequence!'.format(filename))
        if info:
            return ch, midpoint, strand, label, seq, desc
        encoded_seq = self.encoder(seq)
        if encoded_seq is None:
            print('In {} sequence is more than 5% unknown values - sequence removed from dataset'.format(ID))
            self.to_remove.append(ID)
            return None, None
        X = torch.tensor(encoded_seq)
        X = X.reshape(1, *X.size())
        y = torch.tensor(label)
        return X, y

    def get_chrs(self, chr_lists):
        indices = [[] for _ in range(len(chr_lists))]
        for i in range(self.__len__()):
            c, _, _, label, seq, _ = self.__getitem__(i, info=True)
            ch = int(c.strip('chr').replace('X', '23').replace('Y', '23'))
            for j, chr_list in enumerate(chr_lists):
                if ch in chr_list:
                    indices[j].append(i)
        return indices

    def get_classes(self, indices=None):
        if indices is None:
            indices = [i for i in range(self.num_seqs)]
        result = {el: [] for el in self.classes}
        for i in indices:
            _, y = self.__getitem__(i)
            if y is not None:
                result[self.classes[y]].append(i)
        for el in self.to_remove:
            self.IDs.remove(el)
            self.num_seqs = len(self.IDs)
        return result
