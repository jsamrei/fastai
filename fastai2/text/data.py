# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/31_text.data.ipynb (unless otherwise specified).

__all__ = ['make_vocab', 'TensorText', 'LMTensorText', 'Numericalize', 'LMDataLoader', 'pad_input', 'SortedDL',
           'TextBlock', 'TextDataBunch']

# Cell
from ..torch_basics import *
from ..data.all import *
from .core import *

# Cell
def make_vocab(count, min_freq=3, max_vocab=60000):
    "Create a vocab of `max_vocab` size from `Counter` `count` with items present more than `min_freq`"
    vocab = [o for o,c in count.most_common(max_vocab) if c >= min_freq]
    for o in reversed(defaults.text_spec_tok): #Make sure all special tokens are in the vocab
        if o in vocab: vocab.remove(o)
        vocab.insert(0, o)
    vocab = vocab[:max_vocab]
    return vocab + [f'xxfake' for i in range(0, 8-len(vocab)%8)]

# Cell
class TensorText(TensorBase):   pass
class LMTensorText(TensorText): pass

# Cell
class Numericalize(Transform):
    "Reversible transform of tokenized texts to numericalized ids"
    def __init__(self, vocab=None, min_freq=3, max_vocab=60000, sep=' '):
        self.vocab,self.min_freq,self.max_vocab,self.sep = vocab,min_freq,max_vocab,sep
        self.o2i = None if vocab is None else defaultdict(int, {v:k for k,v in enumerate(vocab)})

    def setup(self, dsrc):
        if dsrc is None: return
        if self.vocab is None:
            count = Counter(p for o in dsrc for p in o)
            self.vocab = make_vocab(count, min_freq=self.min_freq, max_vocab=self.max_vocab)
            self.o2i = defaultdict(int, {v:k for k,v in enumerate(self.vocab) if v != 'xxfake'})

    def encodes(self, o): return TensorText(tensor([self.o2i  [o_] for o_ in o]))
    def decodes(self, o): return Str(self.sep.join([self.vocab[o_] for o_ in o if self.vocab[o_] != PAD]))

# Cell
#TODO: add backward
@delegates()
class LMDataLoader(TfmdDL):
    def __init__(self, dataset, lens=None, cache=2, bs=64, seq_len=72, num_workers=0, **kwargs):
        self.items = ReindexCollection([(o[0] if isinstance(o, tuple) else o)
                                          for o in dataset], cache=cache)
        self.seq_len = seq_len
        if lens is None: lens = [len(o) for o in self.items]
        self.lens = ReindexCollection(lens, idxs=self.items.idxs)
        # The "-1" is to allow for final label, we throw away the end that's less than bs
        corpus = round_multiple(sum(lens)-1, bs, round_down=True)
        self.bl = corpus//bs #bl stands for batch length
        self.n_batches = self.bl//(seq_len) + int(self.bl%seq_len!=0)
        self.last_len = self.bl - (self.n_batches-1)*seq_len
        self.make_chunks()
        super().__init__(dataset=dataset, bs=bs, num_workers=num_workers, **kwargs)
        self.n = self.n_batches*bs

    def make_chunks(self): self.chunks = Chunks(self.items, self.lens)
    def shuffle_fn(self,idxs):
        self.items.shuffle()
        self.make_chunks()
        return idxs

    def create_item(self, seq):
        if seq>=self.n: raise IndexError
        sl = self.last_len if seq//self.bs==self.n_batches-1 else self.seq_len
        st = (seq%self.bs)*self.bl + (seq//self.bs)*self.seq_len
        txt = self.chunks[st : st+sl+1]
        return LMTensorText(txt[:-1]),txt[1:]

# Cell
@patch
def truncate(self:Str, n):
    words = self.split(' ')[:n]
    return Str(' '.join(words))

# Cell
@typedispatch
def show_batch(x: TensorText, y, samples, ctxs=None, max_n=10, trunc_at=150, **kwargs):
    if ctxs is None: ctxs = get_empty_df(min(len(samples), max_n))
    samples = L((s[0].truncate(trunc_at),*s[1:]) for s in samples)
    ctxs = show_batch[object](x, y, samples, max_n=max_n, ctxs=ctxs, **kwargs)
    display_df(pd.DataFrame(ctxs))
    return ctxs

# Cell
@typedispatch
def show_batch(x: LMTensorText, y, samples, ctxs=None, max_n=10, **kwargs):
    return show_batch[TensorText](x, None, samples, ctxs=ctxs, max_n=max_n, **kwargs)

# Cell
def pad_input(samples, pad_idx=1, pad_fields=0, pad_first=False, backwards=False):
    "Function that collect samples and adds padding. Flips token order if needed"
    pad_fields = L(pad_fields)
    max_len_l = pad_fields.map(lambda f: max([len(s[f]) for s in samples]))
    if backwards: pad_first = not pad_first
    def _f(field_idx, x):
        if field_idx not in pad_fields: return x
        idx = pad_fields.items.index(field_idx) #TODO: remove items if L.index is fixed
        sl = slice(-len(x), sys.maxsize) if pad_first else slice(0, len(x))
        pad =  x.new_zeros(max_len_l[idx]-x.shape[0])+pad_idx
        x1 = torch.cat([pad, x] if pad_first else [x, pad])
        if backwards: x1 = x1.flip(0)
        return retain_type(x1, x)
    return [tuple(map(lambda idxx: _f(*idxx), enumerate(s))) for s in samples]

# Cell
def _default_sort(x): return len(x[0])

@delegates(TfmdDL)
class SortedDL(TfmdDL):
    def __init__(self, dataset, sort_func=None, res=None, **kwargs):
        super().__init__(dataset, **kwargs)
        self.sort_func = _default_sort if sort_func is None else sort_func
        self.res = [self.sort_func(self.do_item(i)) for i in range_of(self.dataset)] if res is None else res
        self.idx_max = np.argmax(self.res)

    def get_idxs(self):
        idxs = super().get_idxs()
        if self.shuffle: return idxs
        return sorted(idxs, key=lambda i: self.res[i], reverse=True)

    def shuffle_fn(self,idxs):
        idxs = np.random.permutation(len(self.dataset))
        idx_max = np.extract(idxs==self.idx_max, idxs)[0]
        idxs[0],idxs[idx_max] = idxs[idx_max],idxs[0]
        sz = self.bs*50
        chunks = [idxs[i:i+sz] for i in range(0, len(idxs), sz)]
        chunks = [sorted(s, key=lambda i: self.res[i], reverse=True) for s in chunks]
        sort_idx = np.concatenate(chunks)

        sz = self.bs
        batches = [sort_idx[i:i+sz] for i in range(0, len(sort_idx), sz)]
        sort_idx = np.concatenate(np.random.permutation(batches[1:-1])) if len(batches) > 2 else np.array([],dtype=np.int)
        sort_idx = np.concatenate((batches[0], sort_idx) if len(batches)==1 else (batches[0], sort_idx, batches[-1]))
        return iter(sort_idx)

# Cell
def TextBlock(vocab=None, is_lm=False):
    return TransformBlock(type_tfms=Numericalize(vocab), dl_type=LMDataLoader if is_lm else SortedDL,
                          dbunch_kwargs={} if is_lm else {'before_batch': pad_input})

# Cell
class TextDataBunch(DataBunch):
    @classmethod
    @delegates(DataBunch.from_dblock)
    def from_folder(cls, path, train='train', valid='valid', valid_pct=None, seed=None, vocab=None, text_vocab=None, is_lm=False, **kwargs):
        "Create from imagenet style dataset in `path` with `train`,`valid`,`test` subfolders (or provide `valid_pct`)."
        splitter = GrandparentSplitter(train_name=train, valid_name=valid) if valid_pct is None else RandomSplitter(valid_pct, seed=seed)
        y_block = [] if is_lm else [CategoryBlock(vocab=vocab)]
        dblock = DataBlock(blocks=(TextBlock(text_vocab, is_lm), *y_block),
                           get_items=get_text_files,
                           splitter=splitter,
                           get_x=read_file,
                           get_y=None if is_lm else parent_label)
        return cls.from_dblock(dblock, path, path=path, **kwargs)

    @classmethod
    @delegates(DataBunch.from_dblock)
    def from_df(cls, df, path='.', valid_pct=0.2, seed=None, text_col=0, label_col=1, label_delim=None, y_block=None,
                text_vocab=None, is_lm=False, **kwargs):
        if y_block is None and not is_lm: y_block = MultiCategoryBlock if is_listy(label_col) and len(label_col) > 1 else CategoryBlock
        if is_lm: y_block = []
        if not isinstance(y_block, list): y_block = [y_block]
        dblock = DataBlock(blocks=(TextBlock(text_vocab, is_lm), *y_block),
                           get_x=ColReader(text_col),
                           get_y=None if is_lm else ColReader(label_col, label_delim=label_delim),
                           splitter=RandomSplitter(valid_pct, seed=seed))
        return cls.from_dblock(dblock, df, path=path, **kwargs)

    @classmethod
    def from_csv(cls, path, csv_fname='labels.csv', header='infer', delimiter=None, **kwargs):
        df = pd.read_csv(Path(path)/csv_fname, header=header, delimiter=delimiter)
        return cls.from_df(df, path=path, **kwargs)

TextDataBunch.from_csv = delegates(to=TextDataBunch.from_df)(TextDataBunch.from_csv)