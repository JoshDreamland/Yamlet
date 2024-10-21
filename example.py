import yamlet
import datetime

opts = yamlet.YamletOptions(functions={'now': datetime.datetime.now})
loader = yamlet.Loader(opts)
t = loader.load_file('yaml-gcl.yaml')
print(t['childtuple']['coolbeans'])
print(t['childtuple2']['coolbeans'])

# Didn't I tell you not to do this?
print(t['horribletuple']['coolbeans'])
print(t['horribletuple2']['coolbeans'])

print(t['other_features']['timestamp'])
print(t['other_features']['two'])

print('Condition 1:', t['c1']['value'])
print('Condition 2:', t['c2']['value'])
print('Condition 3:', t['c3']['value'])

# The following would break because of cycles.
# print(t['recursive']['a'])

print(t['childtuple'].explain_value('coolbeans'))
print(t['childtuple'].explain_value('beans'))
print(t['childtuple2'].explain_value('beans'))
