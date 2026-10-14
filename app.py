"""Mega Mall Wafr Cash — playable prototype. Virtual balances only; NO real payments."""
import os, json, hmac, hashlib, time, sqlite3, secrets
from urllib.parse import parse_qsl
from flask import Flask, request, jsonify, send_from_directory

ROOT=os.path.dirname(os.path.abspath(__file__))
DB=os.environ.get('DATABASE_PATH', os.path.join(ROOT,'megamal.db'))
BOT_TOKEN=os.environ.get('BOT_TOKEN','')
DEMO_MODE=os.environ.get('DEMO_MODE','0')=='1'
app=Flask(__name__, static_folder='static')
CATS={'fashion':{'name':'الأزياء','icon':'👗','level':1,'cost':0},'beauty':{'name':'الجمال','icon':'💄','level':3,'cost':400},'electronics':{'name':'الإلكترونيات','icon':'🎧','level':5,'cost':900},'home':{'name':'المنزل','icon':'🪑','level':8,'cost':1500},'kids':{'name':'الأطفال','icon':'🧸','level':12,'cost':2800}}
ICONS={'fashion':['🧵','👕','👗','👜','👑'],'beauty':['🧴','💄','🪞','💅','💎'],'electronics':['🔌','🎧','⌚','📱','💻'],'home':['🪵','🪑','🛋️','🛏️','🏡'],'kids':['🧩','🧸','🪀','🚲','🎠']}


def conn():
    os.makedirs(os.path.dirname(os.path.abspath(DB)),exist_ok=True)
    c=sqlite3.connect(DB,timeout=20,isolation_level=None)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA busy_timeout=10000')
    return c

def init():
    c=conn();c.executescript('''
CREATE TABLE IF NOT EXISTS players(id TEXT PRIMARY KEY, name TEXT NOT NULL, coins INTEGER NOT NULL DEFAULT 250, energy INTEGER NOT NULL DEFAULT 18, xp INTEGER NOT NULL DEFAULT 0, level INTEGER NOT NULL DEFAULT 1, last_energy INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tiles(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, category TEXT NOT NULL, tier INTEGER NOT NULL, slot INTEGER NOT NULL, UNIQUE(user_id,slot));
CREATE TABLE IF NOT EXISTS shops(user_id TEXT NOT NULL, category TEXT NOT NULL, PRIMARY KEY(user_id,category));
CREATE TABLE IF NOT EXISTS assets(id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id TEXT NOT NULL, category TEXT NOT NULL, tier INTEGER NOT NULL DEFAULT 4, status TEXT NOT NULL DEFAULT 'owned');
CREATE TABLE IF NOT EXISTS listings(id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id TEXT NOT NULL, asset_id INTEGER NOT NULL UNIQUE, price INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active', buyer_id TEXT, created_at INTEGER NOT NULL, sold_at INTEGER);
CREATE TABLE IF NOT EXISTS rush_rounds(user_id TEXT PRIMARY KEY, started_at INTEGER NOT NULL, deadline INTEGER NOT NULL, stage INTEGER NOT NULL, served INTEGER NOT NULL DEFAULT 0, misses INTEGER NOT NULL DEFAULT 0, orders TEXT NOT NULL, reward_claimed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, kind TEXT NOT NULL, amount INTEGER NOT NULL, info TEXT NOT NULL, created_at INTEGER NOT NULL);
''');c.close()

def stage_reward(stage,seconds_left,misses):
    return 35 + stage*12 + min(35,seconds_left) - min(30,misses*5)

def add_ledger(c,u,kind,amount,info):
    c.execute('INSERT INTO ledger(user_id,kind,amount,info,created_at) VALUES(?,?,?,?,?)',(u,kind,amount,info,int(time.time())))

def auth_user():
    raw=request.headers.get('X-Telegram-Init-Data','')
    if raw and BOT_TOKEN:
        d=dict(parse_qsl(raw,keep_blank_values=True))
        got=d.pop('hash','')
        msg='\n'.join(f'{k}={v}' for k,v in sorted(d.items()))
        key=hmac.new(b'WebAppData',BOT_TOKEN.encode(),hashlib.sha256).digest()
        expected=hmac.new(key,msg.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(got,expected): raise ValueError('توقيع تليجرام غير صالح')
        if abs(time.time()-int(d.get('auth_date',0)))>86400: raise ValueError('جلسة تليجرام منتهية')
        obj=json.loads(d.get('user','{}'))
        if not isinstance(obj.get('id'),int): raise ValueError('حساب غير صالح')
        return 'tg:'+str(obj['id']),str(obj.get('first_name','لاعب'))[:50]
    if DEMO_MODE and not raw:
        demo=request.headers.get('X-Demo-Player','1')
        if demo not in ('1','2','3'): raise ValueError('مستخدم تجريبي غير صالح')
        return 'demo:'+demo,('دعاء','نور','عمر')[int(demo)-1]
    raise ValueError('افتح اللعبة من تليجرام')

@app.errorhandler(Exception)
def err(e):
    app.logger.exception('Request error')
    return jsonify(error=str(e) if isinstance(e,ValueError) else 'حدث خطأ، حاولي مرة أخرى'),400 if isinstance(e,ValueError) else 500

def player(c,u,name):
    p=c.execute('SELECT * FROM players WHERE id=?',(u,)).fetchone()
    if p is None:
        c.execute('INSERT INTO players(id,name,last_energy) VALUES(?,?,?)',(u,name,int(time.time())))
        c.execute('INSERT INTO shops VALUES(?,?)',(u,'fashion'))
        for slot,tier in enumerate([1,1,1,2,2,1]):
            c.execute('INSERT INTO tiles(user_id,category,tier,slot) VALUES(?,?,?,?)',(u,'fashion',tier,slot))
        p=c.execute('SELECT * FROM players WHERE id=?',(u,)).fetchone()
    return p

def snapshot(c,u):
    p=dict(c.execute('SELECT * FROM players WHERE id=?',(u,)).fetchone())
    unlocked=[r['category'] for r in c.execute('SELECT category FROM shops WHERE user_id=?',(u,))]
    tiles=[dict(r) for r in c.execute('SELECT id,category,tier,slot FROM tiles WHERE user_id=? ORDER BY slot',(u,))]
    assets=[dict(r) for r in c.execute('SELECT id,category,tier FROM assets WHERE owner_id=? AND status="owned" ORDER BY id DESC',(u,))]
    listings=[dict(r) for r in c.execute('SELECT l.id,l.asset_id,l.price,l.seller_id,p.name seller_name,a.category,a.tier FROM listings l JOIN assets a ON a.id=l.asset_id JOIN players p ON p.id=l.seller_id WHERE l.status="active" ORDER BY l.created_at DESC,l.id DESC LIMIT 100')]
    mylist=[x for x in listings if x['seller_id']==u]
    transactions=[dict(r) for r in c.execute('SELECT kind,amount,info,created_at FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 8',(u,))]
    rr=c.execute('SELECT * FROM rush_rounds WHERE user_id=?',(u,)).fetchone()
    rush=None
    if rr:
        rush={'stage':rr['stage'],'served':rr['served'],'misses':rr['misses'],'deadline':rr['deadline'],'finished':bool(rr['reward_claimed']),'total':len(json.loads(rr['orders']))}
        if rr['served']<rush['total'] and not rr['reward_claimed'] and time.time()<rr['deadline']:
            rush['order']=json.loads(rr['orders'])[rr['served']]
    return dict(rush=rush,player=p,unlocked=unlocked,tiles=tiles,assets=assets,listings=listings,mylist=mylist,ledger=transactions, categories=CATS, icons=ICONS,demomode=DEMO_MODE,real_money_enabled=False)

@app.route('/')
def home(): return send_from_directory('static','index.html')
@app.route('/health')
def health(): return jsonify(ok=True,game='Mega Mall Wafr Cash',real_money=False)
@app.route('/api/state')
def state():
    u,n=auth_user();c=conn()
    try:
        c.execute('BEGIN IMMEDIATE');player(c,u,n);out=snapshot(c,u);c.commit();return jsonify(out)
    finally:c.close()

@app.route('/api/action',methods=['POST'])
def action():
    u,n=auth_user();d=request.get_json(silent=True) or {};cmd=d.get('action');c=conn()
    try:
        c.execute('BEGIN IMMEDIATE');p=player(c,u,n)
        if cmd=='rush_start':
            prev=c.execute('SELECT * FROM rush_rounds WHERE user_id=?',(u,)).fetchone()
            if prev and prev['served']<len(json.loads(prev['orders'])) and time.time()<prev['deadline'] and not prev['reward_claimed']:
                raise ValueError('فيه جولة شغالة بالفعل!')
            # Every round is free; purchases and energy never affect scoring.
            stage=max(1,min(12,int(d.get('stage',1)))) if isinstance(d.get('stage',1),int) else 1
            if stage>min(12,1+p['level']//3):raise ValueError('المرحلة دي لسه مقفولة')
            import random
            items=['👗','👜','💄','🧴','🎧','📱','🪑','🧸']
            rng=random.SystemRandom()
            count=5+min(7,stage)
            # An order is the exact icon to tap among 8 visible products.
            orders=[rng.choice(items[:min(8,4+(stage//2))]) for _ in range(count)]
            now=int(time.time())
            duration=max(35,80-stage*3)
            c.execute('INSERT OR REPLACE INTO rush_rounds(user_id,started_at,deadline,stage,served,misses,orders,reward_claimed) VALUES(?,?,?,?,0,0,?,0)',(u,now,now+duration,stage,json.dumps(orders,ensure_ascii=False)))
        elif cmd=='rush_serve':
            rr=c.execute('SELECT * FROM rush_rounds WHERE user_id=?',(u,)).fetchone()
            if not rr or rr['reward_claimed']:raise ValueError('ابدئي جولة جديدة')
            orders=json.loads(rr['orders'])
            if rr['served']>=len(orders):raise ValueError('الجولة خلصت')
            if time.time()>rr['deadline']:raise ValueError('الوقت خلص؛ ابدئي جولة جديدة')
            item=d.get('item')
            if item not in ['👗','👜','💄','🧴','🎧','📱','🪑','🧸']:raise ValueError('منتج غير معروف')
            if item!=orders[rr['served']]:
                misses=rr['misses']+1
                # Wrong answers do not award coins and never shorten the timer.
                c.execute('UPDATE rush_rounds SET misses=? WHERE user_id=?',(misses,u))
            else:
                served=rr['served']+1
                c.execute('UPDATE rush_rounds SET served=? WHERE user_id=?',(served,u))
                if served==len(orders):
                    remaining=max(0,rr['deadline']-int(time.time()))
                    reward=max(30,stage_reward(rr['stage'],remaining,rr['misses']))
                    gained_xp=25+rr['stage']*8
                    xp=p['xp']+gained_xp;level=min(50,1+xp//80)
                    c.execute('UPDATE players SET coins=coins+?,xp=?,level=? WHERE id=?',(reward,xp,level,u))
                    c.execute('UPDATE rush_rounds SET reward_claimed=1 WHERE user_id=?',(u,))
                    # Material drop is fixed and non-cash; continue legacy crafting loop.
                    occupied={r['slot'] for r in c.execute('SELECT slot FROM tiles WHERE user_id=?',(u,))}
                    unlocked={r['category'] for r in c.execute('SELECT category FROM shops WHERE user_id=?',(u,))}
                    cat='fashion' if rr['stage']%2 else ('beauty' if 'beauty' in unlocked else 'fashion')
                    for slot in [i for i in range(25) if i not in occupied][:2]:
                        c.execute('INSERT INTO tiles(user_id,category,tier,slot) VALUES(?,?,?,?)',(u,cat,2 if rr['stage']>=3 else 1,slot))
                    add_ledger(c,u,'rush',reward,'خدمة زبائن المول - المرحلة '+str(rr['stage']))
        elif cmd=='generate':
            if c.execute('SELECT count(*) n FROM tiles WHERE user_id=?',(u,)).fetchone()['n']>=25:raise ValueError('اللوحة ممتلئة؛ ادمجي قطعًا أولًا')
            cat=d.get('category','fashion')
            if cat not in CATS or not c.execute('SELECT 1 FROM shops WHERE user_id=? AND category=?',(u,cat)).fetchone():raise ValueError('المحل ده لسه مقفول')
            occupied={r['slot'] for r in c.execute('SELECT slot FROM tiles WHERE user_id=?',(u,))}
            slot=next(i for i in range(25) if i not in occupied)
            c.execute('INSERT INTO tiles(user_id,category,tier,slot) VALUES(?,?,1,?)',(u,cat,slot))
            # Unlimited optional crafting materials: no energy wait in V2.
        elif cmd=='merge':
            a,b=d.get('first'),d.get('second')
            if not isinstance(a,int) or not isinstance(b,int) or a==b:raise ValueError('اختاري قطعتين مختلفتين')
            rows=c.execute('SELECT * FROM tiles WHERE user_id=? AND id IN (?,?)',(u,a,b)).fetchall()
            if len(rows)!=2 or rows[0]['category']!=rows[1]['category'] or rows[0]['tier']!=rows[1]['tier']:raise ValueError('لازم قطعتين من نفس النوع والمستوى')
            if rows[0]['tier']>=5:raise ValueError('وصلتي لأعلى درجة: اصنعي منها أصلًا')
            c.execute('DELETE FROM tiles WHERE id=?',(rows[1]['id'],))
            c.execute('UPDATE tiles SET tier=tier+1 WHERE id=?',(rows[0]['id'],))
            gained=10*rows[0]['tier'];xp=p['xp']+gained
            level=min(50,1+xp//80)
            c.execute('UPDATE players SET coins=coins+?,xp=?,level=? WHERE id=?',(12*rows[0]['tier'],xp,level,u))
            add_ledger(c,u,'merge',12*rows[0]['tier'],'دمج قطعتين')
        elif cmd=='craft':
            tid=d.get('tile_id');tile=c.execute('SELECT * FROM tiles WHERE user_id=? AND id=?',(u,tid)).fetchone()
            if not tile or tile['tier']<4:raise ValueError('التصنيع يبدأ من قطعة مستوى 4')
            cost=100 if tile['tier']==4 else 250
            if p['coins']<cost:raise ValueError('عملات المول مش كافية للتصنيع')
            c.execute('DELETE FROM tiles WHERE id=?',(tid,))
            c.execute('INSERT INTO assets(owner_id,category,tier) VALUES(?,?,?)',(u,tile['category'],tile['tier']))
            c.execute('UPDATE players SET coins=coins-? WHERE id=?',(cost,u))
            add_ledger(c,u,'craft',-cost,'صناعة أصل رقمي')
        elif cmd=='unlock':
            cat=d.get('category');info=CATS.get(cat)
            if not info:raise ValueError('محل غير معروف')
            if c.execute('SELECT 1 FROM shops WHERE user_id=? AND category=?',(u,cat)).fetchone():raise ValueError('المحل مفتوح بالفعل')
            if p['level']<info['level'] or p['coins']<info['cost']:raise ValueError('محتاج مستوى أعلى أو عملات أكثر')
            c.execute('INSERT INTO shops VALUES(?,?)',(u,cat))
            c.execute('UPDATE players SET coins=coins-? WHERE id=?',(info['cost'],u))
            add_ledger(c,u,'unlock',-info['cost'],'فتح '+info['name'])
        elif cmd=='energy':
            now=int(time.time())
            # Legacy button supported without cooldown.
            c.execute('UPDATE players SET energy=min(25,energy+5),last_energy=? WHERE id=?',(now,u))
        elif cmd=='list':
            aid=d.get('asset_id');price=d.get('price')
            if not isinstance(price,int) or price<20 or price>10000:raise ValueError('السعر بين 20 و10,000 عملة')
            asset=c.execute('SELECT * FROM assets WHERE id=? AND owner_id=? AND status="owned"',(aid,u)).fetchone()
            if not asset:raise ValueError('الأصل غير متاح للبيع')
            c.execute('UPDATE assets SET status="listed" WHERE id=?',(aid,))
            c.execute('INSERT INTO listings(seller_id,asset_id,price,created_at) VALUES(?,?,?,?)',(u,aid,price,int(time.time())))
        elif cmd=='cancel':
            lid=d.get('listing_id');listing=c.execute('SELECT * FROM listings WHERE id=? AND seller_id=? AND status="active"',(lid,u)).fetchone()
            if not listing:raise ValueError('العرض غير متاح')
            c.execute('UPDATE listings SET status="cancelled" WHERE id=?',(lid,))
            c.execute('UPDATE assets SET status="owned" WHERE id=?',(listing['asset_id'],))
        elif cmd=='buy':
            lid=d.get('listing_id');listing=c.execute('SELECT * FROM listings WHERE id=? AND status="active"',(lid,)).fetchone()
            if not listing:raise ValueError('العرض اتباع أو اتلغى')
            if listing['seller_id']==u:raise ValueError('ما ينفعش تشتري أصل بتاعك')
            if p['coins']<listing['price']:raise ValueError('رصيدك غير كافي')
            fee=max(1,(listing['price']*10+99)//100);net=listing['price']-fee
            c.execute('UPDATE players SET coins=coins-? WHERE id=?',(listing['price'],u))
            c.execute('UPDATE players SET coins=coins+? WHERE id=?',(net,listing['seller_id']))
            c.execute('UPDATE assets SET owner_id=?,status="owned" WHERE id=?',(u,listing['asset_id']))
            c.execute('UPDATE listings SET status="sold",buyer_id=?,sold_at=? WHERE id=?',(u,int(time.time()),lid))
            add_ledger(c,u,'buy',-listing['price'],'شراء أصل من لاعب')
            add_ledger(c,listing['seller_id'],'sale',net,'بيع أصل — خصم عمولة 10%')
            add_ledger(c,'platform','fee',fee,'عمولة بيع افتراضية')
        else:raise ValueError('إجراء غير معروف')
        out=snapshot(c,u);c.commit();return jsonify(out)
    except Exception:
        c.rollback();raise
    finally:c.close()

init()
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=False)
