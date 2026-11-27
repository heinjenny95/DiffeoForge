"""Python3.8-compatible runtime bytes; native objective/gradient remain unchanged."""

SOURCE = rb'''"""Fixed invertible coordinates for the same native L-BFGS objective.

Physical native coefficients x = x0 + B z; chain-rule gradient B.T g.
Neither native objective/gradient values nor accepted physical states are edited.
"""
import hashlib,json
from collections import OrderedDict
from pathlib import Path
import numpy as np

def bind(original_minimize,operator_path,expected_sha256,*,trace_path=None):
    path=Path(operator_path)
    assert hashlib.sha256(path.read_bytes()).hexdigest()==expected_sha256
    B=np.load(path,allow_pickle=False)
    assert B.dtype==np.float64 and B.ndim==2 and B.shape[0]==B.shape[1]
    assert np.isfinite(B).all() and np.array_equal(B,B.T)
    smallest=float(np.linalg.eigvalsh(B).min());assert smallest>0
    n=B.shape[0]
    def minimize(fun,x0,*args,**kwargs):
        assert not args and kwargs.get('jac') is True
        assert kwargs.get('method')=='L-BFGS-B' and kwargs.get('bounds') is None
        x0=np.asarray(x0);assert x0.dtype==np.float64 and x0.shape==(n*3,)
        x0=x0.copy();cache=OrderedDict();calls=[0];callbacks=[0]
        options=dict(kwargs.get('options') or {})
        physical_gtol=float(options.get('gtol',1e-5))
        coordinate_gtol=physical_gtol*smallest/np.sqrt(n*3)
        assert np.isfinite(coordinate_gtol) and coordinate_gtol>0
        kwargs=dict(kwargs,options=dict(options,gtol=coordinate_gtol))
        def physical(z):return x0+(B@np.asarray(z).reshape(n,3)).ravel()
        def key(x):return hashlib.sha256(x.tobytes()).hexdigest()
        def cost(z):
            x=physical(z);f,g=fun(x)
            g=np.asarray(g);assert g.shape==x.shape and g.dtype==np.float64
            # Save exact native physical f/g, rather than invert a rounded
            # transformed gradient when returning the final native result.
            cache[key(x)]=(float(f),g.copy());calls[0]+=1
            if len(cache)>64:cache.popitem(last=False)
            return f,(B.T@g.reshape(n,3)).ravel()
        original_callback=kwargs.get('callback')
        if original_callback is not None:
            def callback(z):
                callbacks[0]+=1
                return original_callback(physical(z))
            kwargs=dict(kwargs,callback=callback)
        try:
            result=original_minimize(cost,np.zeros_like(x0),**kwargs)
            x=physical(result.x);f,g=cache[key(x)]
            assert float(result.fun).hex()==f.hex()
            result.x=x;result.jac=g;result.fun=f
            return result
        finally:
            if trace_path is not None:
                p=Path(trace_path)
                with p.open('x',encoding='utf-8') as stream:
                    json.dump(dict(version='retain-linear-coordinates-v1',
                        operator_sha256=expected_sha256,controls=n,
                        native_objective_calls=calls[0],physical_callbacks=callbacks[0],
                        physical_f_g_returned_unchanged=True,
                        map='x=x0+Bz; gradient_z=B.T gradient_x',
                        physical_gtol=physical_gtol, coordinate_gtol=coordinate_gtol,
                        minimum_operator_eigenvalue=smallest,
                        native_solver='unchanged SciPy L-BFGS-B'),stream,indent=2)
    return minimize
'''
