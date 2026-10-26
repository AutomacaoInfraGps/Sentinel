"""Coleta evidencias do FortiAnalyzer e FortiManager sem expor credenciais."""
from __future__ import annotations
import argparse, ctypes, json, re, shutil, sys, time
from datetime import datetime
from pathlib import Path
from access_review_progress import publish_detail, publish_progress
from windows_evidence import capture_monitor

CODE_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__import__("os").environ["SENTINEL_ACCESS_REVIEW_HOME"])
SECRETS=("FORTIANALYZER_USUARIO","FORTIANALYZER_SENHA","FORTIMANAGER_USUARIO","FORTIMANAGER_SENHA")

def env(path):
    from access_review_credentials import load_credentials
    return load_credentials(path, SECRETS)

def largest_monitor():
    if sys.platform!="win32": return None
    class R(ctypes.Structure): _fields_=[("left",ctypes.c_long),("top",ctypes.c_long),("right",ctypes.c_long),("bottom",ctypes.c_long)]
    class I(ctypes.Structure): _fields_=[("size",ctypes.c_ulong),("monitor",R),("work",R),("flags",ctypes.c_ulong)]
    found=[]; cbtype=ctypes.WINFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(R),ctypes.c_long)
    def cb(h,*_):
        i=I(); i.size=ctypes.sizeof(I)
        if ctypes.windll.user32.GetMonitorInfoW(h,ctypes.byref(i)): found.append({"x":i.work.left,"y":i.work.top,"width":i.work.right-i.work.left,"height":i.work.bottom-i.work.top})
        return 1
    ctypes.windll.user32.SetProcessDPIAware(); ctypes.windll.user32.EnumDisplayMonitors(None,None,cbtype(cb),0)
    return max(found,key=lambda x:x["width"]*x["height"],default=None)

def vis(loc):
    try:
        for i in range(loc.count()):
            if loc.nth(i).is_visible(): return loc.nth(i)
    except Exception: pass

def control(page, names, timeout=30):
    names=names if isinstance(names,(list,tuple,set)) else [names]; end=time.monotonic()+timeout
    while time.monotonic()<end:
        for f in page.frames:
            for n in names:
                for loc in (f.get_by_text(n,exact=True),f.get_by_role("button",name=n,exact=True),f.get_by_role("link",name=n,exact=True)):
                    x=vis(loc)
                    if x: return x
        time.sleep(.25)
    raise RuntimeError("Controle nao encontrado: "+" / ".join(map(str,names)))

def selector(page, sels, label, timeout=30):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        for f in page.frames:
            for s in sels:
                x=vis(f.locator(s))
                if x: return x
        time.sleep(.25)
    raise RuntimeError("Controle nao encontrado: "+label)

def settle(page):
    try: page.wait_for_load_state("networkidle",timeout=5000)
    except Exception: pass
    time.sleep(1)

def shot(page,path):
    settle(page); page.evaluate("() => window.scrollTo(0,0)"); path.parent.mkdir(parents=True,exist_ok=True)
    capture_monitor(page,path)

def login(page,url,user,password):
    page.goto(url,wait_until="domcontentloaded")
    try:
        u=selector(page,["input[name='username']","input[name='user']","input[type='text']","input[placeholder='Username']","input[placeholder*='User' i]","[role=textbox]","[contenteditable=true]"],"usuario",5)
        p=selector(page,["input[name='password']","input[type='password']","input[placeholder='Password']","input[placeholder*='Pass' i]"],"senha",5)
        u.fill(user); p.fill(password)
    except RuntimeError:
        # Fortinet antigo renderiza os campos por componentes que podem nao
        # expor os inputs. A geometria do painel e centralizada e responsiva.
        size=page.evaluate("() => ({w:innerWidth,h:innerHeight})")
        page.mouse.click(size["w"]*.5,size["h"]*.474); page.keyboard.type(user)
        page.mouse.click(size["w"]*.5,size["h"]*.527); page.keyboard.type(password)
    b=vis(page.get_by_role("button",name=re.compile("login|sign in|entrar",re.I))) or selector(page,["button[type='submit']","input[type='submit']"],"login")
    b.click(); settle(page)

def click(page,name):
    x=control(page,name); x.scroll_into_view_if_needed(); x.click(); settle(page)

def click_or_point(page,name,x_ratio,y_ratio,timeout=4):
    try:
        item=control(page,name,timeout); box=item.bounding_box()
        if not box: raise RuntimeError("Controle sem geometria")
        page.mouse.click(box["x"]+box["width"]/2,box["y"]+box["height"]/2)
    except Exception:
        size=page.evaluate("() => ({w:innerWidth,h:innerHeight})")
        page.mouse.click(size["w"]*x_ratio,size["h"]*y_ratio)
    settle(page)

def adom_dialog_visible(page):
    pattern=re.compile(r"^\s*Select an ADOM\s*$",re.I)
    for frame in page.frames:
        if vis(frame.get_by_text(pattern)):
            return True
    return False

def named_control_visible(page, name):
    for frame in page.frames:
        for loc in (frame.get_by_text(name,exact=True),frame.get_by_role("button",name=name,exact=True),frame.get_by_role("link",name=name,exact=True)):
            if vis(loc):
                return True
    return False

def wait_adom_opened(page, expected, timeout=12):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if not adom_dialog_visible(page) and named_control_visible(page,expected):
            settle(page)
            return not adom_dialog_visible(page) and named_control_visible(page,expected)
        time.sleep(.25)
    return False

def open_adom(page,name,expected):
    try:
        pattern=re.compile(re.escape(name),re.I)
        candidates=[]
        for frame in page.frames:
            items=frame.get_by_text(pattern)
            for index in range(items.count()):
                item=items.nth(index)
                if not item.is_visible(): continue
                box=item.bounding_box()
                if box and box["width"]>20 and box["height"]>10:
                    candidates.append((box["width"]*box["height"],item))
        if candidates:
            candidates.sort(key=lambda value:value[0])
            item=candidates[0][1]
            item.scroll_into_view_if_needed()
            box=item.bounding_box()
            for action in ("click","enter","double"):
                if action=="click": item.click(force=True)
                elif action=="enter": item.press("Enter")
                elif box: page.mouse.dblclick(box["x"]+box["width"]/2,box["y"]+box["height"]/2)
                if wait_adom_opened(page,expected): return
    except Exception:
        pass
    size=page.evaluate("() => ({w:innerWidth,h:innerHeight})")
    for ratio in (.21,.237,.285,.30):
        page.mouse.click(size["w"]*.5,size["h"]*ratio); settle(page)
        if wait_adom_opened(page,expected,5): return
        page.mouse.dblclick(size["w"]*.5,size["h"]*ratio); settle(page)
        if wait_adom_opened(page,expected,5): return
    raise RuntimeError(f"Nao foi possivel abrir o ADOM: {name}")

def tables(page):
    result=[]
    for f in page.frames:
        for sel in ("table","[role=grid]"):
            for i in range(f.locator(sel).count()):
                t=f.locator(sel).nth(i)
                if not t.is_visible(): continue
                rows=t.locator("tr,[role=row]").all_inner_texts()
                rows=[re.sub(r"\s+"," ",r).strip() for r in rows if r.strip()]
                if rows: result.extend(rows)
    return list(dict.fromkeys(result))

def logout(page):
    for label in ("Logout","Log Out","Sign Out"):
        try: control(page,label,2).click(); settle(page); return True
        except Exception: pass
    # Menu de usuario no canto superior direito.
    size=page.evaluate("() => ({w:innerWidth})"); page.mouse.click(size["w"]-35,20); time.sleep(.5)
    for label in ("Logout","Log Out","Sign Out"):
        try: control(page,label,2).click(); settle(page); return True
        except Exception: pass
    return False

def discover_devices(page):
    names=[]; unchanged=0
    for _ in range(60):
        state=page.evaluate("""
        () => {
          const valid = e => {
            const r=e.getBoundingClientRect(), t=(e.innerText||'').trim();
            return r.width>0 && r.height>0 && r.x>=240 && r.x<=500 && /^FGT_[A-Z0-9_&.-]+$/i.test(t);
          };
          const items=[...document.querySelectorAll('*')].filter(valid);
          const marker=[...document.querySelectorAll('*')].find(e => {
            const r=e.getBoundingClientRect(), t=(e.innerText||'').trim();
            return r.width>0 && r.height>0 && r.x>=240 && r.x<=500 && /^NAO_INTEGRADOS(?:\s*\(\d+\))?$/i.test(t);
          });
          let scroller=null;
          const anchor=items[0] || marker;
          if(anchor){
            for(let p=anchor.parentElement;p;p=p.parentElement){
              if(p.scrollHeight>p.clientHeight+20){scroller=p;break;}
            }
          }
          const before=scroller ? scroller.scrollTop : 0;
          const maximum=scroller ? scroller.scrollHeight-scroller.clientHeight : 0;
          if(scroller) scroller.scrollTop=Math.min(maximum,before+Math.max(300,scroller.clientHeight*.75));
          return {names:items.map(e=>(e.innerText||'').trim()),marker:!!marker,before,maximum,after:scroller?scroller.scrollTop:0};
        }
        """)
        old=len(names)
        for value in state["names"]:
            if value not in names: names.append(value)
        unchanged = unchanged+1 if len(names)==old else 0
        if state["marker"] or state["after"]>=state["maximum"] or unchanged>=2: break
        time.sleep(.15)
    if not names: raise RuntimeError("Nenhum dispositivo encontrado na arvore Managed FortiGate")
    return names

def device_search(page):
    for f in page.frames:
        for i in range(f.locator("input").count()):
            item=f.locator("input").nth(i)
            if not item.is_visible(): continue
            box=item.bounding_box()
            if box and 240 <= box["x"] <= 520 and box["y"] < 100: return item
    raise RuntimeError("Campo de busca da lista de dispositivos nao encontrado")

def open_device(page,name):
    search=device_search(page); search.fill(name); time.sleep(.5)
    for f in page.frames:
        loc=f.get_by_text(name,exact=True)
        for i in range(loc.count()):
            item=loc.nth(i)
            if not item.is_visible(): continue
            box=item.bounding_box()
            if box and 240 <= box["x"] <= 550:
                item.click(); settle(page); return
    raise RuntimeError("Dispositivo nao encontrado no painel esquerdo: "+name)

def open_device_administrators(page):
    # Menu horizontal da configuracao do FortiGate, acima da tabela.
    candidates=[]
    for f in page.frames:
        loc=f.get_by_text(re.compile(r"^System(?::.*)?$",re.I))
        for i in range(loc.count()):
            item=loc.nth(i)
            if item.is_visible():
                box=item.bounding_box()
                if box and box["x"]>500 and box["y"]<130: candidates.append(item)
    if not candidates: raise RuntimeError("Menu System do FortiGate nao encontrado")
    candidates[0].click(); time.sleep(.4)
    for f in page.frames:
        loc=f.get_by_text("Administrators",exact=True)
        for i in range(loc.count()):
            item=loc.nth(i)
            if not item.is_visible(): continue
            box=item.bounding_box()
            if box and box["x"]>500 and box["y"]<250:
                item.click(force=True); settle(page); return
    raise RuntimeError("Administrators do menu System do FortiGate nao encontrado")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--config",type=Path,required=True); ap.add_argument("--credentials",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); ap.add_argument("--headless",action="store_true"); ap.add_argument("--cdp-url"); a=ap.parse_args()
    if a.headless: raise ValueError("O modo headless não pode gerar evidências porque não exibe a barra de tarefas do Windows.")
    cfg=json.loads(a.config.read_text(encoding="utf-8-sig")); sec=env(a.credentials); out=a.output.resolve(); out.mkdir(parents=True,exist_ok=True)
    archive=None; existing=list(out.glob("*.png"))
    if existing:
        arc=ROOT/"dados"/"execucoes"/"Firewalls"/"prints_substituidos"/datetime.now().strftime("%Y%m%d-%H%M%S"); arc.mkdir(parents=True)
        for p in existing: shutil.move(str(p),str(arc/p.name))
        archive=str(arc)
    result={"executado_em":datetime.now().astimezone().isoformat(timespec="seconds"),"capturas":[],"regionais":[],"arquivo_anterior":archive,"logout":{}}
    diag=ROOT/"dados"/"execucoes"/"Firewalls"; diag.mkdir(parents=True,exist_ok=True); step="inicio"
    for stale in (diag/"Erro-AuditoriaFirewalls.json",diag/"Erro-AuditoriaFirewalls.png"):
        stale.unlink(missing_ok=True)
    from playwright.sync_api import sync_playwright
    mon=largest_monitor(); args=["--disable-translate","--disable-features=msEdgeTranslate,Translate,TranslateUI"]
    args += ["--start-maximized"] if not mon else [f"--window-position={mon['x']},{mon['y']}",f"--window-size={mon['width']},{mon['height']}"]
    with sync_playwright() as pw:
        external_browser=bool(a.cdp_url)
        browser=pw.chromium.connect_over_cdp(a.cdp_url) if external_browser else pw.chromium.launch(channel=cfg.get("browser_channel","msedge"),headless=a.headless,args=args)
        opts={"ignore_https_errors": cfg.get("verify_tls", True) is False}; opts["viewport" if a.headless else "no_viewport"] = cfg.get("viewport",{"width":1920,"height":1080}) if a.headless else True
        ctx=browser.new_context(**opts); ctx.set_default_timeout(int(cfg.get("timeout_seconds",45))*1000); page=ctx.new_page()
        if not a.headless:
            s=ctx.new_cdp_session(page); wid=s.send("Browser.getWindowForTarget")["windowId"]; s.send("Browser.setWindowBounds",{"windowId":wid,"bounds":{"windowState":"maximized"}})
        try:
            step="FortiAnalyzer login"; publish_progress('fortianalyzer_login',18); login(page,cfg["fortianalyzer_url"],sec["FORTIANALYZER_USUARIO"],sec["FORTIANALYZER_SENHA"])
            step="FortiAnalyzer ADOM"; publish_progress('fortianalyzer_adom',27); open_adom(page,cfg["fortianalyzer_adom"],"System Settings")
            step="FortiAnalyzer Administrators"; click_or_point(page,"System Settings",.065,.417); click_or_point(page,"Administrators",.07,.50); control(page,re.compile(r"System Administrator",re.I),10); shot(page,out/"p014_1.png"); result["capturas"].append("p014_1.png"); result["fortianalyzer_administrators"]=tables(page); result["logout"]["fortianalyzer"]=logout(page)
            step="FortiManager login"; publish_progress('fortimanager_login',38); login(page,cfg["fortimanager_url"],sec["FORTIMANAGER_USUARIO"],sec["FORTIMANAGER_SENHA"])
            step="FortiManager ADOM"; publish_progress('fortimanager_adom',46); open_adom(page,cfg["fortimanager_adom"],"Device Manager")
            step="FortiManager Device & Groups"; click(page,"Device Manager"); click(page,"Device & Groups")
            shot(page,out/"p005_1.png"); result["capturas"].append("p005_1.png"); result["managed_fortigates"]=tables(page)
            devices=discover_devices(page); result["dispositivos_descobertos"]=devices
            step="FortiManager Administrators"; click(page,"System Settings"); click(page,"Administrators"); shot(page,out/"p008_1.png"); result["capturas"].append("p008_1.png"); result["fortimanager_administrators"]=tables(page)
            step="retorno aos dispositivos"; click(page,"Device Manager"); click(page,"Device & Groups")
            for index,name in enumerate(devices):
                publish_detail('Administradores do firewall', target=name)
                publish_progress('firewall_devices', 56 + int(((index + 1) / max(len(devices), 1)) * 14), current=index + 1, total=len(devices))
                step=f"regional {index+1}: {name}"; open_device(page,name)
                if index==0: open_device_administrators(page)
                filename=f"regional_{index+1:03}.png"
                shot(page,out/filename); result["capturas"].append(filename); result["regionais"].append({"ordem":index+1,"dispositivo":name,"evidencia":filename,"administradores":tables(page)})
            result["logout"]["fortimanager"]=logout(page)
            publish_progress('collecting_done',74)
        except Exception as e:
            publish_detail(step, status='warning', error=e)
            (diag/"Erro-AuditoriaFirewalls.json").write_text(json.dumps({"etapa":step,"erro":"Falha na coleta da area.","tipo":type(e).__name__},ensure_ascii=False,indent=2),encoding="utf-8")
            try: capture_monitor(page,diag/"Erro-AuditoriaFirewalls.png")
            except Exception: pass
            raise RuntimeError(f"Falha na etapa '{step}': {e}") from e
        finally:
            ctx.close()
            if not external_browser: browser.close()
    (diag/"Resultado-AuditoriaFirewalls.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"capturas":len(result["capturas"]),"regionais":len(result["regionais"]),"logout":result["logout"]},ensure_ascii=False))
if __name__=="__main__":
    try: main()
    except Exception as e: print("FALHA:",e,file=sys.stderr); raise SystemExit(1)
