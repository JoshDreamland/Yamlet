import yamlet

loader = yamlet.DynamicScopeLoader()
t = loader.load('yaml-gcl.yaml')
print(t['childtuple']['coolbeans'])
print(t['childtuple2']['coolbeans'])

# Didn't I tell you not to do this?
print(t['horribletuple']['coolbeans'])
print(t['horribletuple2']['coolbeans'])
