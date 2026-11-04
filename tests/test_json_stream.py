"""Streaming artifacts retain stdlib JSON values, grammar and bounded reads."""
import io
import json
import pytest
from litreview.json_stream import load

VALID = ['null','true','false','0','-0.0','1234567890123456789012345678901234567890',
         '1.2345678901234567e-123','1e400','1e-400','NaN','Infinity','-Infinity',
         '"escaped \\"quote\\" and \\\\ slash"','"\\u03bc\\uD83D\\uDE00"',
         '[]','{}','{"a":1,"a":2}',
         json.dumps({'unicode':'\u00b5M \u27e6P1\u27e7','values':[1,True,None,{'nested':[]}],
                     'multiline':'one\r\ntwo','quotes':'"\\/'},ensure_ascii=False),
         ' \r\n {"x": [ {}, [], -2, 0.5, false ]} \t ']

@pytest.mark.parametrize('text',VALID)
@pytest.mark.parametrize('chunk_size',[1,2,7,65536])
def test_stream_preserves_stdlib_values(text,chunk_size):
    expected=json.loads(text)
    actual=load(io.StringIO(text),chunk_size=chunk_size)
    assert json.dumps(actual,ensure_ascii=True)==json.dumps(expected,ensure_ascii=True)

INVALID=['',' ','{','[','{"a"','{"a":','{"a":1,}','[1,]','[1 2]','{"a" 1}',
         '{a:1}','true false','01','1e','1e+','--1','trueX','[}','{]','"unterminated',
         '"bad\\q"','"bad\\uZZZZ"','"bad\\u12"','"control\n"','{"x":undefined}']

@pytest.mark.parametrize('text',INVALID)
@pytest.mark.parametrize('chunk_size',[1,7,65536])
def test_invalid_document_never_becomes_an_accepted_artifact(text,chunk_size):
    with pytest.raises(json.JSONDecodeError):json.loads(text)
    with pytest.raises(json.JSONDecodeError):load(io.StringIO(text),chunk_size=chunk_size)


def test_no_unbounded_read_or_full_document_join():
    payload=[{'finding_id':str(i),'constraint':'synthetic qualification '*12} for i in range(5000)]
    text=json.dumps(payload)
    class Bounded(io.StringIO):
        calls=0
        def read(self,size=-1):
            assert 0<size<=65536
            self.calls+=1
            return super().read(size)
    stream=Bounded(text)
    assert load(stream)==payload and stream.calls>10


def test_bad_escape_is_rejected_before_reading_unrelated_remainder():
    class Bounded(io.StringIO):
        calls=0
        def read(self,size=-1):
            self.calls+=1
            assert self.calls<4
            return super().read(size)
    with pytest.raises(json.JSONDecodeError):load(Bounded('"bad\\q"'+' '*1000000))


def test_deep_containers_do_not_add_python_recursion_pressure():
    text='['*80+'{"x":true}'+']'*80
    assert load(io.StringIO(text),chunk_size=7)==json.loads(text)
