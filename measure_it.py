from time import time
from functools import wraps
from contextlib import contextmanager
import inspect

__all__ = ['measure_iter', 'measure_each', 'measure_first', 'measure_reduce',
           'measure_produce', 'measure_func', 'measure_block']

def print_metric(name, count, elapsed):
    """A metric function that prints
    
    :arg str name: name of the metric
    :arg int count: number of elements
    :arg float elapsed: time in seconds
    """
    if name is not None:
        print("%s: %d elements in %.2f seconds"%(name, count, elapsed))
    else:
        print("%d elements in %.2f seconds"%(count, elapsed))


default_metric = print_metric #: user-supplied function to use as global default metric

def call_default(name, count, elapsed):
    """call the :func:`default_metric` global in this module
    
    :arg str name: name of the metric
    :arg int count: number of elements
    :arg float elapsed: time in seconds
    """
    return default_metric(name, count, elapsed)
    

def measure_iter(iterable, metric = call_default, name = None):
    """Measure total time and element count for consuming an iterable

    :arg iterable: any iterable
    :arg function metric: f(name, count, total_time)
    :arg str name: name for the metric
    """
    total_time = 0
    count = 0
    it = enumerate(iterable, 1) # count, element
    try:
        while True:
            t = time()
            try:
                count, x = next(it)
            finally:
                total_time += time() - t
            yield x
    finally:
        # underlying iterable is exhausted (StopIteration) or errored. Record
        # the `metric` and allow exception to propogate
        metric(name, count, total_time)

# deprecated alias for measure_iter
measure = measure_iter

def measure_each(iterable, metric = call_default, name = None):
    """Measure time elapsed to produce each item of an iterable

    :arg iterable: any iterable
    :arg function metric: f(name, 1, time)
    :arg str name: name for the metric
    """
    it = iter(iterable)
    while True:
        t = time()
        try:
            x = next(it)
        except StopIteration:
            # don't record a metric for final next() call
            raise
        except Exception:
            # record a metric for other exceptions, than raise
            metric(name, 1, time() - t)
            raise
        else:
            # normal path, record metric and yield
            metric(name, 1, time() - t)
            yield x

def measure_first(iterable, metric = call_default, name = None):
    """Measure time elapsed to produce first item of an iterable

    :arg iterable: any iterable
    :arg function metric: f(name, 1, time)
    :arg str name: name for the metric
    """
    it = iter(iterable)
    t = time()
    try:
        x = next(it)
    except StopIteration:
        # don't record a metric for final next() call
        raise
    except Exception:
        # record a metric for other exceptions, than raise
        metric(name, 1, time() - t)
        raise
    else:
        # normal path, record metric and yield
        metric(name, 1, time() - t)
        yield x

    for x in it: yield x

def _make_decorator(measuring_func):
    """morass of closures for making decorators/descriptors"""
    def _decorator(metric = call_default, name = None): 
        def wrapper(func):
            
            name_ = name if name is not None else func.__module__ + '.' +func.__name__    
            class measure_it_decorator(object): # must be a class for descriptor magic to work
                @wraps(func)
                def __call__(self, *args, **kwargs):
                    return measuring_func(func(*args, **kwargs), metric, name_)
    
                def __get__(self, instance, class_):
                    name_ = name if name is not None else\
                        ".".join((class_.__module__, class_.__name__, func.__name__))
                    @wraps(func)
                    def wrapped_method(*args, **kwargs):
                        return measuring_func(func(instance, *args, **kwargs), metric, name_)
                    return wrapped_method
            return measure_it_decorator()
        
        return wrapper
    return _decorator

measure_iter.func = _make_decorator(measure_iter)
measure_each.func = _make_decorator(measure_each)
measure_first.func = _make_decorator(measure_first)
def _iterable_to_varargs_func(func):
    """decorator to convert a func taking a iterable to a *args one"""
    def wrapped(*args, **kwargs):
        return func(args, **kwargs)
    return wrapped

def _varargs_to_iterable_func(func):    
    """decorator to convert a *args func to one taking a iterable"""    
    def wrapped(iterable, **kwargs):
        return func(*iterable, **kwargs)
    return wrapped

def _iterable_to_varargs_method(func):
    """decorator to convert a method taking a iterable to a *args one"""
    def wrapped(self, *args, **kwargs):
        return func(self, args, **kwargs)
    return wrapped

def _varargs_to_iterable_method(func):
    """decorator to convert a *args method to one taking a iterable"""
    def wrapped(self, iterable, **kwargs):
        return func(self, *iterable, **kwargs)
    return wrapped

class counted_iterable(object):
    """helper class that wraps an iterable and counts items"""
    __slots__ = ['iterable', 'count']

    def __init__(self, iterable):
        self.iterable = iter(iterable)
        self.count = 0

    def __iter__(self):
        return self

    def __next__(self):
        ret = next(self.iterable)
        self.count += 1
        return ret

    next = __next__ # python2 compatibility

def measure_reduce(metric = call_default, name = None):
    """Decorator to measure a function that consumes many items.
    
    The wrapped `func` should take either a single `iterable` argument or
    `*args` (plus keyword arguments).
    
    :arg function metric: f(name, count, total_time)
    :arg str name: name for the metric
    """
    class measure_reduce_decorator(object):
        def __init__(self, func):
            self.orig_func = func
            self.wrapping = wraps(func)
            self.metric_name = name if name is not None else func.__module__ + '.' +func.__name__
            self.varargs = inspect.getargspec(func).varargs is not None
            if self.varargs:
                self.method = _varargs_to_iterable_method(func)
                self.func = _varargs_to_iterable_func(func)
                self.callme = _iterable_to_varargs_func(self._call)
            else:
                self.method = func                
                self.func = func
                self.callme = self._call

        # we need _call/callme b/c CPython short-circurits CALL_FUNCTION to
        # directly access __call__, bypassing our varargs decorator             
        def __call__(self, *args, **kwargs):
            return self.callme(*args, **kwargs)

        def _call(self, iterable, **kwargs):
            it = counted_iterable(iterable)
            t = time()
            try:
                return self.func(it, **kwargs)
            finally:
                metric(self.metric_name, it.count, time() - t)

        def __get__(self, instance, class_):
            metric_name = name if name is not None else\
                ".".join((class_.__module__, class_.__name__, self.orig_func.__name__))

            def wrapped_method(iterable, **kwargs):
                it = counted_iterable(iterable)
                t = time()
                try:
                    return self.method(instance, it, **kwargs)
                finally:
                    metric(metric_name, it.count, time() - t)
            
            # wrap in func version b/c self is handled for us by descriptor (ie, `instance`)
            if self.varargs: wrapped_method = _iterable_to_varargs_func(wrapped_method)
            wrapped_method = self.wrapping(wrapped_method)
            return wrapped_method
                        
    return measure_reduce_decorator

def measure_produce(metric = call_default, name = None):
    """Decorator to measure a function that produces many items.
    
    The function should return an object that supports `__len__` (ie, a
    list). If the function returns an iterator, use `measure_iter.func()` instead.
    
    :arg function metric: f(name, count, total_time)
    :arg str name: name for the metric
    """

    def wrapper(func):       
        def measurer(name_, *args, **kwargs):
            t = time()            
            try:
                ret = func(*args, **kwargs)
            except Exception:
                # record a metric for other exceptions, than raise
                metric(name_, 0, time() - t)
                raise
            else:
                # normal path, record metric & return
                metric(name_, len(ret), time() - t)
                return ret

        name_ = name if name is not None else func.__module__ + '.' +func.__name__    
        class measure_it_decorator(object): # must be a class for descriptor magic to work
            @wraps(func)
            def __call__(self, *args, **kwargs):
                return measurer(name_, *args, **kwargs)
    
            def __get__(self, instance, class_):
                name_ = name if name is not None else\
                    ".".join((class_.__module__, class_.__name__, func.__name__))
                @wraps(func)
                def wrapped_method(*args, **kwargs):
                    return measurer(name_, instance, *args, **kwargs)
                return wrapped_method
            
        return measure_it_decorator()
    return wrapper

def measure_func(metric = call_default, name = None):
    """Decorator to measure function execution time.
    
    :arg function metric: f(name, 1, total_time)
    :arg str name: name for the metric
    """
    def wrapper(func):       
        def measurer(name_, *args, **kwargs):
            t = time()            
            try:
                return func(*args, **kwargs)
            finally:
                metric(name_, 1, time() - t)

        name_ = name if name is not None else func.__module__ + '.' +func.__name__    
        class measure_it_decorator(object): # must be a class for descriptor magic to work
            @wraps(func)
            def __call__(self, *args, **kwargs):
                return measurer(name_, *args, **kwargs)
    
            def __get__(self, instance, class_):
                name_ = name if name is not None else\
                    ".".join((class_.__module__, class_.__name__, func.__name__))
                @wraps(func)
                def wrapped_method(*args, **kwargs):
                    return measurer(name_, instance, *args, **kwargs)
                return wrapped_method
            
        return measure_it_decorator()
    return wrapper

@contextmanager
def measure_block(metric = call_default, name = None):
    """Context manager to measure execution time of a block
    
    :arg function metric: f(name, 1, time)
    :arg str name: name for the metric
    """
    t = time()
    try:
        yield
    finally:
        metric(name, 1, time() - t)

try:
    from statsd import statsd, StatsClient
    if statsd is None: statsd = StatsClient()
except ImportError:
    pass
else:
    def statsd_metric(name, count, elapsed):
        """Metric that records to `statsd`"""
        with statsd.pipeline() as pipe:
            pipe.incr(name, count)
            pipe.timing(name, int(round(1000 * elapsed)))  # milliseconds

### Matplotlib ###
import struct
import tempfile
import warnings

import numpy as np
import prettytable

class NumpyStatsMetric(object):

    struct = struct.Struct('<Id')
    dtype = np.dtype([('count', np.uint32), ('elapsed', np.float64)])            
    table = None
    _metrics = {}
    
    def __init__(self, name):
        self.name = name
        self.temp = tempfile.TemporaryFile(mode = 'w+b', buffering = 32768)
    
    def record(self, count, elapsed):
        self.temp.write(self.struct.pack(count, elapsed))
    
    @classmethod
    def metric(cls, name, count, elapsed):
        if name is None:
            warnings.warn("Ignoring unnamed metric", stacklevel=3)
            return
        
        try:
            self = cls._metrics[name]
        except KeyError:
            self = cls._metrics[name] = cls(name)
        
        self.record(count, elapsed)
    
    def dump(self):
        try:
            self.temp.seek(0) # seek to beginning            
            arr = np.fromfile(self.temp, self.dtype)
            self.table.add_row([self.name,           
                                np.mean(arr['count']),
                                np.std(arr['count']),
                                np.mean(arr['elapsed']),
                                np.std(arr['elapsed'])])

        finally:
            self.temp.close()
    
    def iter_records(self):
        return (self.struct.unpack(x) for x in
                iter(lambda: self.temp.read(self.struct.size), b''))
    
    @classmethod
    def dump_all(cls):
        cls.table = prettytable.PrettyTable(['Name', 'Count Mean', 'Count Stddev', 'Time Mean', 'Time Stddev'])
        cls.table.set_style(prettytable.PLAIN_COLUMNS)
        cls.table.sortby = 'Name'
        cls.table.align['Name'] = 'l'
        cls.table.float_format = '.2'
        for self in cls._metrics.values():
            self.dump()
        
        print(cls.table)