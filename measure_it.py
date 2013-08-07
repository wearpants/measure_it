from time import time
from functools import wraps
import inspect

__all__ = ['measure', 'measure_each', 'measure_reduce']

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

def measure(iterable, metric = print_metric, name = None):
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

def measure_each(iterable, metric = print_metric, name = None):
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

    
def _iterable_to_varargs(func):
    """decorator to convert a *args func to one taking a iterable"""
    def wrapped(*args, **kwargs):
        return func(args, **kwargs)
    return wrapped

def _varargs_to_iterable(func):
    """decorator to convert a func taking a iterable to a *args one"""
    def wrapped(iterable, **kwargs):
        return func(*iterable, **kwargs)
    return wrapped

def measure_reduce(metric = print_metric, name = None):
    """Decorator to measure a function that consumes many items.
    
    The wrapped `func` should take either a single `iterable` argument or
    `*args` (plus keyword arguments).
    
    :arg function metric: f(name, 1, time)
    :arg str name: name for the metric
    """
    def wrapper(func):
        wrapping = wraps(func)
        varargs = inspect.getfullargspec(func).varargs is not None
        if varargs:
            func = _varargs_to_iterable(func)
            
        def wrapped(iterable, **kwargs):
            it = iter(iterable)
            count = 0
            
            def counted_iterable():
                nonlocal count
                for i in it:
                    count += 1
                    yield i

            t = time()
            try:
                return func(counted_iterable(), **kwargs)
            finally:
                metric(name, count, time() - t)
        
        if varargs:
            wrapped = _iterable_to_varargs(wrapped)

        return wrapping(wrapped)
    return wrapper

def _make_decorator(measuring_func):
    """morass of closures for making decorators/descriptors"""
    def _decorator(metric = print_metric, name = None): 
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

measure.func = _make_decorator(measure)
measure_each.func = _make_decorator(measure_each)

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