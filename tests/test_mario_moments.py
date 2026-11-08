"""Pure logic of the scored-moments list used by the Mario Land viewer agent."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import mario_moments as M  # noqa: E402


def test_moments_logic():
    g=np.zeros((16,20),int);g[10,5]=1
    assert not M.enemy_near(g); g[10,8]=4; assert M.enemy_near(g); g[10,8]=0; g[10,9]=4; assert not M.enemy_near(g)
    assert M.classify(100,False,True,g)=='bonus' and M.classify(100,True,False,g)=='coin'
    e=lambda f,k,p=100,a='1-1',mv=3:{'frame':f,'move':mv,'area':a,'x':f,'y':5,'kind':k,'points':p}
    s=M.group([e(10,'kill'),e(50,'kill'),e(60,'bonus'),e(500,'coin'),e(510,'coin',a='1-2')])
    assert [len(x) for x in s]==[2,1,1],s
    d={'worker':1,'seq':list(range(40))}
    m=M.to_moment(s[0],d);assert m['kills']==2 and m['rank']==200+600+200 and len(m['seq'])==7, m
    b=M.MomentBook(keep=2);b.add([e(10,'kill')],d);b.add([e(10,'kill')],d);assert len(b.moments)==1
    b.add([e(900,'coin'),],d);b.add([e(2000,'kill',300)],d);assert len(b.moments)==2 and b.ranked()[0]['points']==300
