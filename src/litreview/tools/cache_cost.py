"""Offline conditional cache scenarios. No provider calls or token counting."""
def estimate(shared_tokens,variable_tokens,output_tokens,*,input_rate=2.,write_rate=2.5,read_rate=.1,output_rate=10.,ttl_seconds=1800,gaps=None,caching=True):
    if len(variable_tokens)!=len(output_tokens):raise ValueError('One output allowance per work unit is required')
    if shared_tokens<0 or any(x<0 for x in variable_tokens+output_tokens):raise ValueError('Negative token allowance')
    gaps=[0]+[0]*(len(variable_tokens)-1) if gaps is None else gaps
    if len(gaps)!=len(variable_tokens) or any(g<0 for g in gaps):raise ValueError('One nonnegative interval per work unit is required')
    uncached=writes=reads=outputs=0
    for i,(v,o,gap) in enumerate(zip(variable_tokens,output_tokens,gaps)):
        uncached+=v;outputs+=o
        if not caching:uncached+=shared_tokens
        elif i==0 or gap>=ttl_seconds:writes+=shared_tokens
        else:reads+=shared_tokens
    parts={'input':uncached*input_rate/1e6,'cache_write':writes*write_rate/1e6,'cache_read':reads*read_rate/1e6,'output':outputs*output_rate/1e6}
    return {'basis':'MODELED; assumes stated warm/cold state and unchanged outputs, not guaranteed hits or billed costs',
            'uncached_input_tokens':uncached,'cache_write_tokens':writes,'cache_read_tokens':reads,'output_tokens':outputs,
            'cost_parts_usd':parts,'total_usd':sum(parts.values())}
