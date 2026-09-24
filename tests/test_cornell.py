from pathlib import Path
import importlib.util

spec = importlib.util.spec_from_file_location('standalone_note_quality', Path(__file__).parents[1] / 'vendor' / 'note_quality.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
normalize = module.normalize_cornell


def test_equal_length_arrays_do_not_imply_semantic_pairs():
    value = {'cues': ['阈值？', '公式？'], 'notes': ['CPI=EV/AC', '小于1成本超支'], 'summary': '保留'}
    result = normalize(value)
    assert result['pairs'] == []
    assert result['pairing_status'] == 'unpaired'
    assert result['cues'] == value['cues'] and result['notes'] == value['notes']
    assert normalize(result) == result


def test_explicit_pairs_remain_intact():
    value = {'pairs': [{'cue': '公式？', 'note': 'CPI=EV/AC'}], 'summary': '保留'}
    result = normalize(value)
    assert result['pairs'] == value['pairs']
    assert result['pairing_status'] == 'paired'


def test_non_string_pair_values_are_not_stringified():
    value = {'pairs': [
        {'cue': None, 'note': '有效答案'},
        {'cue': '数字？', 'note': 7},
        {'cue': {'text': '对象问题'}, 'note': {'text': '对象答案'}},
    ]}
    result = normalize(value)
    assert result['pairing_status'] == 'unpaired'
    assert result['pairs'] == [
        {'cue': '', 'note': '有效答案'},
        {'cue': '数字？', 'note': ''},
    ]
    assert 'None' not in repr(result)
    assert normalize(result) == result
