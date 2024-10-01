import yamlet
import datetime

opts = yamlet.YamletOptions(functions={'now': datetime.datetime.now})
loader = yamlet.DynamicScopeLoader(opts)
t = loader.load('yaml-gcl.yaml')
print(t['childtuple']['coolbeans'])
print(t['childtuple2']['coolbeans'])

# Didn't I tell you not to do this?
print(t['horribletuple']['coolbeans'])
print(t['horribletuple2']['coolbeans'])

print(t['other_features']['timestamp'])
print(t['other_features']['two'])

# The following would break because of cycles.
# print(t['recursive']['a'])
