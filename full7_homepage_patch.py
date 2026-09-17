"""Put the FULL-7 7-file contract on the Render homepage.

The SPEC v1.1 Joint-Outcome card is removed from the homepage. This patch must run
after spec11_joint_core_patch.apply_patch so it sees the live INDEX_HTML.
"""
from __future__ import annotations

from typing import Any

FULL7_CARD = r'''
  <div class="c" id="full7-card">
    <h2>FULL-7 Contract</h2>
    <p class="s">7 Pre-Match-Dateien · keine Odds · SPIELEN nur BTTS · 1X2 und Totals höchstens BEOBACHTEN</p>
    <p class="s">Match · League · Form · Table · Player · Referee · Manager</p>
    <input id="full7Files" type="file" multiple accept=".json,application/json">
    <p id="full7Pick" class="s">Noch keine Dateien ausgewählt.</p>
    <button id="go7">FULL-7 auswerten</button>
    <div id="full7Out"></div>
  </div>
'''

FULL7_SCRIPT = r'''
function classifyFull7(files){
  const slots={
    match_file:null,league_file:null,form_file:null,table_file:null,
    player_file:null,referee_file:null,manager_file:null
  };
  const rules=[
    ["referee_file",/referee/i],
    ["manager_file",/manager/i],
    ["player_file",/player/i],
    ["table_file",/table/i],
    ["form_file",/form/i],
    ["league_file",/league/i],
    ["match_file",/match/i]
  ];
  for(const file of files){
    for(const [slot,re] of rules){
      if(slots[slot]) continue;
      if(re.test(file.name)){slots[slot]=file;break;}
    }
  }
  return slots;
}
function pct(value){
  if(value==null||isNaN(Number(value))) return "—";
  return (Number(value)*100).toFixed(1)+"%";
}
function renderCards(items, emptyText){
  if(!items||!items.length) return '<p class="s">'+escapeHtml(emptyText)+'</p>';
  return '<div class="g">'+items.map(function(item){
    return '<div class="m"><div class="s">'+escapeHtml(item.family||"")+' · '+escapeHtml(item.market||"")+'</div>'+
      '<div class="b">'+escapeHtml(item.decision||"")+'</div>'+
      '<div class="s">'+escapeHtml(pct(item.probability))+' · '+escapeHtml(item.reason||"")+'</div></div>';
  }).join("")+'</div>';
}
function matchIds(obj){
  const root=(obj&&obj.payload&&obj.payload.data)||(obj&&obj.data)||obj||{};
  return {home:Number(root.homeID), away:Number(root.awayID)};
}
function slimLeague(obj, homeId, awayId){
  try{
    const rows=obj&&obj.payload&&obj.payload.team_pages&&obj.payload.team_pages.data;
    if(Array.isArray(rows)){
      obj.payload.team_pages.data=rows.filter(function(row){
        const id=Number(row&&row.id);
        return id===homeId||id===awayId;
      });
    }
  }catch(e){}
  return obj;
}
function slimPlayer(obj, homeId, awayId){
  try{
    const pages=obj&&obj.payload&&obj.payload.pages;
    if(!Array.isArray(pages)) return obj;
    const rows=[];
    pages.forEach(function(page){
      (page.data||[]).forEach(function(row){
        const id=Number(row&&row.club_team_id);
        if(id===homeId||id===awayId) rows.push(row);
      });
    });
    obj.payload.pages=[{success:true,data:rows,pager:{current_page:1,max_page:1}}];
    if(obj._footystats_meta){
      obj._footystats_meta.pagination_complete=true;
      obj._footystats_meta.max_page='1';
    }
  }catch(e){}
  return obj;
}
function jsonFile(name, obj){
  return new File([JSON.stringify(obj)], name, {type:'application/json'});
}
(function hideLegacySpecCard(){
  const go=document.getElementById("go");
  if(go){
    const card=go.closest(".c");
    if(card && card.id!=="full7-card") card.remove();
  }
  ["bundleFiles","folderFiles"].forEach(function(id){
    const el=document.getElementById(id);
    if(el){
      const card=el.closest(".c");
      if(card && card.id!=="full7-card") card.remove();
      else el.remove();
    }
  });
})();
const full7Input=document.getElementById("full7Files");
const full7Pick=document.getElementById("full7Pick");
function showPicked(){
  if(!full7Input||!full7Pick) return;
  const files=[...(full7Input.files||[])];
  if(!files.length){
    full7Pick.textContent="Noch keine Dateien ausgewählt.";
    return;
  }
  const lines=files.map(function(f){
    const mb=f.size/1048576;
    const size=mb>=0.1? (mb.toFixed(2)+" MB") : (Math.max(1,Math.round(f.size/1024))+" KB");
    return f.name+" ("+size+")";
  });
  full7Pick.textContent=files.length+" Datei(en): "+lines.join(" | ");
}
if(full7Input&&full7Pick){
  ["change","input","click","blur"].forEach(function(ev){
    full7Input.addEventListener(ev, showPicked);
  });
  setInterval(showPicked, 400);
}
const go7=document.getElementById("go7");
if(go7){
  go7.onclick=async function(){
    showPicked(); const files=[...((full7Input&&full7Input.files)||[])];
    const out=document.getElementById("full7Out")||document.getElementById("out");
    if(out&&out.scrollIntoView) try{out.scrollIntoView({block:"nearest"});}catch(e){}
    const slots=classifyFull7(files);
    const missing=Object.keys(slots).filter(function(key){return !slots[key];});
    if(missing.length){
      out.innerHTML='<div class="c bad"><b>FULL-7 braucht 7 Dateien.</b><p class="s">Es fehlen: '+escapeHtml(missing.join(", "))+'</p></div>';
      return;
    }
    go7.disabled=true;
    const listed=[...files].map(function(f){return f.name;}).join(', ');
    try{
      out.innerHTML='<div class="c">Geladen: '+escapeHtml(listed)+'<br>Dateien werden verkleinert…</div>';
      const parsed={};
      for(const key of Object.keys(slots)){
        parsed[key]=JSON.parse(await slots[key].text());
      }
      const ids=matchIds(parsed.match_file);
      slimLeague(parsed.league_file, ids.home, ids.away);
      slimPlayer(parsed.player_file, ids.home, ids.away);
      const form=new FormData();
      Object.keys(parsed).forEach(function(key){
        form.append(key, jsonFile(slots[key].name, parsed[key]));
      });
      out.innerHTML='<div class="c">Geladen: '+escapeHtml(listed)+'<br>Sende kompaktes Paket…</div>';
      const response=await fetch('/api/full7/predict',{method:'POST',body:form});
      const data=await response.json();
      if(!response.ok||!data.ok){
        out.innerHTML='<div class="c"><h3 class="bad">FULL-7 nicht möglich</h3><pre>'+escapeHtml(JSON.stringify(data,null,2))+'</pre></div>';
        return;
      }
      const ident=data.identity||{};
      const engine=data.engine||{};
      const sample=(engine.sample_security||{}).status||"—";
      const families=engine.families||{};
      const familyRows=Object.keys(families).map(function(name){
        const row=families[name]||{};
        return '<tr><td>'+escapeHtml(name)+'</td><td>'+escapeHtml(row.selected_market||"")+'</td>'+
          '<td>'+escapeHtml(row.decision||"")+'</td><td>'+escapeHtml(pct(row.base_probability))+'</td>'+
          '<td class="s">'+escapeHtml(row.decision_reason||"")+'</td></tr>';
      }).join("");
      out.innerHTML=
        '<div class="c"><div class="ok"><b>FULL-7 Contract</b></div>'+
        '<p class="s">'+escapeHtml(String(ident.home_name||ident.home_id||"?"))+' vs '+escapeHtml(String(ident.away_name||ident.away_id||"?"))+
        ' · '+escapeHtml(String((data.contract||{}).release_status||""))+'</p>'+
        '<div class="g">'+
        '<div class="m"><div class="s">SPIELEN erlaubt</div><div class="b">BTTS</div></div>'+
        '<div class="m"><div class="s">Stichprobe</div><div class="b">'+escapeHtml(sample)+'</div></div>'+
        '<div class="m"><div class="s">Playable</div><div class="b">'+escapeHtml(String((engine.playable||[]).length))+'</div></div>'+
        '</div></div>'+
        '<div class="c"><h3>Playable</h3>'+renderCards(engine.playable,"Kein SPIELEN.")+'</div>'+
        '<div class="c"><h3>Blocked</h3>'+renderCards(engine.blocked,"—")+'</div>'+
        '<div class="c"><h3>Familien</h3><table><tr><th>Familie</th><th>Markt</th><th>Decision</th><th>p</th><th>Grund</th></tr>'+familyRows+'</table></div>';
    }catch(error){
      out.innerHTML='<div class="c bad">Fehler: '+escapeHtml(String(error))+'</div>';
    }finally{
      go7.disabled=false;
    }
  };
}
'''


def apply_full7_homepage(legacy: Any) -> Any:
    html = legacy.INDEX_HTML
    if 'id="full7-card"' not in html:
        if "<div class=\"w\">" in html:
            html = html.replace("<div class=\"w\">", "<div class=\"w\">" + FULL7_CARD, 1)
        if "</script>" in html:
            html = html.replace("</script>", FULL7_SCRIPT + "\n</script>", 1)
    if "<style>" in html and "#go,.c:has(#go)" not in html:
        html = html.replace("<style>", "<style>\n#go,.c:has(#go){display:none!important}\n", 1)
    html = html.replace(
        "<title>FootyStats SPEC v1.1 · Joint-Outcome Engine</title>",
        "<title>FULL-7 Contract · FootyStats</title>",
    )
    html = html.replace(
        "<h2>SPEC v1.1 · Joint-Outcome Engine</h2>",
        "<h2>Legacy · SPEC v1.1 Joint-Outcome</h2>",
    )
    html = html.replace(
        "<h3>5 Dateien eines Spiels auswählen</h3>",
        "<h3>Nur wenn FULL-7 nicht geht: 5 Dateien</h3>",
    )
    legacy.INDEX_HTML = html
    return legacy
