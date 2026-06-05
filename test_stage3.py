import sys
sys.stdout.reconfigure(encoding='utf-8')
from src.entity_state import EntityState
from src.entity_state import _init_stereotype_trees
from src.language_system.stereotype_learner import quick_learn, StereotypeLearner
from src.language_system.stereotype_tree import StereotypeTree, ensure_tree

e = EntityState()
_init_stereotype_trees(e)

# bcyq
for i in range(5):
    quick_learn(e, 'bcyq', 'What do you think about understanding?', 0.2)

tree = e._stereotype_trees.get('default')
print(f'Individuals after bcyq: {list(tree._individuals.keys())}')
bcyq_node = tree._individuals.get('bcyq')
print(f'bcyq tags: {bcyq_node.tags}')
print()

# xiaozhang features (simulate separately)
learner = StereotypeLearner()
xiaozhang_history = [
    {'text': 'Tell me the specific steps.', 'emotion': 0.1}
    for _ in range(5)
]
features = learner._extractor.extract(xiaozhang_history)
print(f'xiaozhang features: {features}')
print()

# Manually call register_with_similarity
print('Calling register_with_similarity for xiaozhang...')
result = tree.register_with_similarity('xiaozhang', features, ['test'])
print(f'Result: {result}')

xiaozhang_node = tree._individuals.get('xiaozhang')
print(f'xiaozhang path: {xiaozhang_node.path if xiaozhang_node else None}')
