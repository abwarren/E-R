(function(){
  'use strict';

  if(window._n4p){clearInterval(window._n4p);window._n4p=null;}

  var API='https://nuts4poker.com/collector/save';
  var last='',count=0;
  var seatHands=new Map();
  var lastBoard=null;

  // Full table state (HUD data)
  var seats=[];
  var pot={text:'',amount:0};
  var dealer=-1;

  // Find skillgames iframe or fall back to document
  function getRootDoc(){
    var frames=document.querySelectorAll('iframe');
    for(var i=0;i<frames.length;i++){
      var src=String(frames[i].src||'');
      if(src.indexOf('skillgames')!==-1||src.indexOf('18751019')!==-1){
        try{
          var doc=frames[i].contentDocument||(frames[i].contentWindow&&frames[i].contentWindow.document);
          if(doc)return doc;
        }catch(e){}
      }
    }
    return document;
  }

  // Parse card from CSS class: icon-layer2_{suit}{rank}_p-c-d → "Ah"
  function parseCard(cls){
    if(!cls)return null;
    var m=cls.match(/icon-layer2_([hdcs])(a|k|q|j|10|[2-9])_p-c-d/i);
    if(!m)return null;
    var R={a:'A',k:'K',q:'Q',j:'J','10':'T'};
    return(R[m[2].toLowerCase()]||m[2].toUpperCase())+m[1].toLowerCase();
  }

  // Get unique cards from .single-cart-view-p children
  function getCards(el){
    if(!el)return[];
    var cards=[],seen=new Set();
    var els=el.querySelectorAll('.single-cart-view-p');
    for(var i=0;i<els.length;i++){
      var c=parseCard(els[i].getAttribute('class')||'');
      if(c&&!seen.has(c)){seen.add(c);cards.push(c);}
    }
    return cards;
  }

  function parseMoney(text){
    if(!text)return 0;
    return parseFloat(text.replace(/[^0-9.,]/g,'').replace(',','.'))||0;
  }

  function safeText(el){
    return(el&&(el.innerText||el.textContent)||'').trim();
  }

  // Get board cards (≥3 required)
  function getBoard(){
    var doc=getRootDoc();
    var boardEl=doc.querySelector('sg-poker-board');
    if(boardEl){
      var cards=[],seen=new Set();
      var els=boardEl.querySelectorAll('.single-cart-view-p');
      for(var i=0;i<els.length;i++){
        if(els[i].closest('sg-poker-table-seat')||els[i].closest('.player-mini-container-p'))continue;
        var c=parseCard(els[i].getAttribute('class')||'');
        if(c&&!seen.has(c)){seen.add(c);cards.push(c);}
      }
      if(cards.length>=3)return cards.join('');
    }
    var containers=doc.querySelectorAll('.carts-container-p');
    for(var j=0;j<containers.length;j++){
      if(!containers[j].closest('.player-mini-container-p')){
        var fc=getCards(containers[j]);
        if(fc.length>=3)return fc.join('');
      }
    }
    return null;
  }

  // Get pot
  function getPot(){
    var doc=getRootDoc();
    var el=doc.querySelector('.pot-w-view-p')||doc.querySelector('.pot-amount')||doc.querySelector('.total-pot');
    if(el){var t=safeText(el);return{text:t,amount:parseMoney(t)};}
    return{text:'',amount:0};
  }

  // Get dealer position
  function getDealer(){
    var doc=getRootDoc();
    var el=doc.querySelector('.dealer-icon-view');
    if(el){var m=String(el.className||'').match(/position-(\d+)/);if(m)return Number(m[1]);}
    return-1;
  }

  // Scan seats — full state + accumulate cards
  function scanSeats(){
    var doc=getRootDoc();
    var seatEls=doc.querySelectorAll('sg-poker-table-seat');
    if(!seatEls.length)seatEls=doc.querySelectorAll('.player-mini-container-p');

    var result=[];
    for(var i=0;i<seatEls.length;i++){
      var seat=seatEls[i];
      var pm=String(seat.className||'').match(/position-(\d+)/);
      var idx=pm?Number(pm[1]):i;
      var s={seat:idx};

      // Name
      var nameEl=seat.querySelector('p.single-win-item-sizes')||seat.querySelector('.player-name')||seat.querySelector('[class*="name"]');
      if(nameEl)s.name=safeText(nameEl);

      // Stack
      var stackEl=seat.querySelector('.player-text-info-p span b')||seat.querySelector('.player-stack')||seat.querySelector('[class*="stack"]');
      if(stackEl)s.stack=parseMoney(safeText(stackEl));

      // Hero / sitting out / active / folded
      s.isHero=seat.classList.contains('self-player');
      s.sittingOut=seat.classList.contains('seat-out-v')||!!seat.querySelector('.seat-out-v');
      s.isActive=seat.classList.contains('active')||!!seat.querySelector('.active-turn');
      s.folded=seat.classList.contains('folded')||!!seat.querySelector('.folded');

      // Action
      var actEl=seat.querySelector('.action-indicator')||seat.querySelector('.player-action')||seat.querySelector('[class*="action-text"]');
      if(actEl){
        var t=safeText(actEl).toUpperCase();
        if(t.indexOf('FOLD')!==-1)s.action='FOLD';
        else if(t.indexOf('CHECK')!==-1)s.action='CHECK';
        else if(t.indexOf('ALL')!==-1){s.action='ALL_IN';s.actionSize=parseMoney(safeText(actEl));}
        else if(t.indexOf('RAISE')!==-1){s.action='RAISE';s.actionSize=parseMoney(safeText(actEl));}
        else if(t.indexOf('CALL')!==-1){s.action='CALL';s.actionSize=parseMoney(safeText(actEl));}
        else if(t.indexOf('BET')!==-1){s.action='BET';s.actionSize=parseMoney(safeText(actEl));}
      }

      // Cards — accumulate for collector
      var container=seat.querySelector('.carts-container-p');
      var cards=getCards(container||seat);
      if(cards.length>=4&&cards.length<=7){
        var cardStr=cards.join('');
        s.cards=cardStr;
        seatHands.set(idx,cardStr);
      }else if(seatHands.has(idx)){
        s.cards=seatHands.get(idx);
      }

      result.push(s);
    }
    seats=result;
    pot=getPot();
    dealer=getDealer();
  }

  // Detect new deal (board disappeared or shrank)
  function detectNewDeal(){
    var board=getBoard();
    if((lastBoard&&!board)||(lastBoard&&board&&board.length<lastBoard.length)){
      seatHands.clear();
      lastBoard=board||null;
      return;
    }
    lastBoard=board;
  }

  // Build card-only text snapshot for collector
  function buildSnapshot(){
    if(seatHands.size===0)return null;
    var lines=[];
    var sorted=[...seatHands.entries()].sort(function(a,b){return a[0]-b[0];});
    for(var i=0;i<sorted.length;i++)lines.push(sorted[i][1]);
    var board=getBoard();
    if(board)lines.push('BOARD:'+board);
    return lines.join('\n');
  }

  // POST card data → collector → engine hands input
  function postToN4P(text){
    var lines=text.split('\n').filter(Boolean);
    var hands=lines.filter(function(l){return!/^BOARD:/i.test(l)&&/^[2-9TJQKA][shdc]/i.test(l)&&l.length>=8;});
    if(hands.length<2||hands.length>9)return;
    var x=new XMLHttpRequest();
    x.open('POST',API);
    x.setRequestHeader('Content-Type','application/json');
    x.onload=function(){
      try{
        var d=JSON.parse(x.responseText);
        if(!d.dup){count++;console.log('[N4P] #'+count+' ('+hands.length+'h):\n'+text);}
      }catch(e){}
    };
    x.onerror=function(){console.error('[N4P] POST failed');};
    x.send(JSON.stringify({text:text}));
  }

  function tick(){
    detectNewDeal();
    scanSeats();
    var snapshot=buildSnapshot();
    if(!snapshot||seatHands.size<2||snapshot===last)return;
    last=snapshot;
    postToN4P(snapshot);
  }

  // Full table state for HUD / bot_runner / other consumers
  window._n4p=setInterval(tick,1500);
  window._n4p_injected=true;
  window._n4p_buildSnapshot=function(){
    var hands=[];
    seatHands.forEach(function(v){hands.push(v);});
    return{hands:hands,board:lastBoard,count:count};
  };
  window._n4pTable=function(){
    return{seats:seats,pot:pot,dealer:dealer,board:lastBoard,count:count};
  };

  tick();
  console.log('[N4P] v8.1 loaded');
})();
