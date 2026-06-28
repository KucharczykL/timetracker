class Component extends DCLogic {
  H = React.createElement;

  C = {
    text:'#e8eaf2', muted:'#8b90a6', faint:'#6b7290',
    border:'#2a2f42', panel:'#161922', panel2:'#1b1f2e',
    AND:'#7bd88f', OR:'#ffb454', NOT:'#ff6b81', REL:'#5cc8ff', QUANT:'#b18cff', input:'#10121b'
  };

  ROOTS = ['Game','Session','Purchase','PlayEvent','Device'];
  BASE = { Game:5243, Session:48910, Purchase:3187, PlayEvent:6754, Device:23, Platform:41 };

  SCHEMA = {
    Game: { label:'Game', plural:'Games', dot:'#7bd88f',
      fields:[
        {key:'name', label:'Name', type:'string'},
        {key:'status', label:'Status', type:'enum', options:['Unplayed','Played','Finished','Retired','Abandoned']},
        {key:'mastered', label:'Mastered', type:'bool'},
        {key:'year_released', label:'Year released', type:'int'},
        {key:'playtime', label:'Playtime', type:'duration'},
      ],
      relations:[
        {key:'sessions', label:'Sessions', target:'Session', many:true},
        {key:'playevents', label:'Play events', target:'PlayEvent', many:true},
        {key:'purchases', label:'Purchases', target:'Purchase', many:true},
        {key:'platform', label:'Platform', target:'Platform', many:false},
      ] },
    Session: { label:'Session', plural:'Sessions', dot:'#5cc8ff',
      fields:[
        {key:'duration_total', label:'Duration', type:'duration'},
        {key:'timestamp_start', label:'Started', type:'date'},
        {key:'emulated', label:'Emulated', type:'bool'},
        {key:'note', label:'Note', type:'string'},
      ],
      relations:[
        {key:'game', label:'Game', target:'Game', many:false},
        {key:'device', label:'Device', target:'Device', many:false},
      ] },
    Purchase: { label:'Purchase', plural:'Purchases', dot:'#ffb454',
      fields:[
        {key:'price', label:'Price', type:'float'},
        {key:'ownership_type', label:'Ownership', type:'enum', options:['Physical','Digital','Digital Upgrade','Rented','Borrowed','Trial','Demo','Pirated']},
        {key:'type', label:'Kind', type:'enum', options:['Game','DLC','Season Pass','Battle Pass']},
        {key:'date_purchased', label:'Purchased', type:'date'},
        {key:'date_refunded', label:'Refunded', type:'date_nullable'},
        {key:'num_purchases', label:'Games in bundle', type:'int'},
      ],
      relations:[
        {key:'games', label:'Games', target:'Game', many:true},
        {key:'platform', label:'Platform', target:'Platform', many:false},
      ] },
    PlayEvent: { label:'Play event', plural:'Play events', dot:'#b18cff',
      fields:[
        {key:'started', label:'Started', type:'date_nullable'},
        {key:'ended', label:'Ended', type:'date_nullable'},
        {key:'days_to_finish', label:'Days to finish', type:'int'},
        {key:'note', label:'Note', type:'string'},
      ],
      relations:[ {key:'game', label:'Game', target:'Game', many:false} ] },
    Device: { label:'Device', plural:'Devices', dot:'#ff6b81',
      fields:[
        {key:'name', label:'Name', type:'string'},
        {key:'type', label:'Type', type:'enum', options:['PC','Console','Handheld','Mobile','Single-board computer','Unknown']},
      ],
      relations:[ {key:'sessions', label:'Sessions', target:'Session', many:true} ] },
    Platform: { label:'Platform', plural:'Platforms', dot:'#8b90a6',
      fields:[
        {key:'name', label:'Name', type:'string'},
        {key:'group', label:'Group', type:'string'},
      ],
      relations:[] },
  };

  OPS = {
    string:[['contains','contains'],['eq','is'],['neq','is not'],['starts','starts with'],['empty','is empty']],
    enum:[['eq','is'],['neq','is not']],
    bool:[['true','is true'],['false','is false']],
    number:[['gte','≥'],['lte','≤'],['gt','>'],['lt','<'],['eq','='],['neq','≠'],['between','between']],
    date:[['after','after'],['before','before'],['on','on'],['between','between'],['lastdays','in last … days']],
    date_nullable:[['set','is set'],['unset','is not set'],['after','after'],['before','before'],['between','between']],
  };
  COUNT_OPS = [['gte','≥'],['lte','≤'],['eq','='],['gt','>'],['lt','<']];

  // ---- id ----
  _n = 0;
  uid(){ return 'n'+(++this._n)+'_'+Math.random().toString(36).slice(2,6); }

  state = { rootModel:'Game', tree:this.defaultTreeFor('Game'), dragId:null, dropId:null };

  // ---- schema helpers ----
  typeGroup(t){ if(t==='int'||t==='float'||t==='duration') return 'number'; return t; }
  field(model,key){ return (this.SCHEMA[model].fields.find(f=>f.key===key)) || this.SCHEMA[model].fields[0]; }
  relation(model,key){ return this.SCHEMA[model].relations.find(r=>r.key===key); }

  defaultOp(f){ const g=this.typeGroup(f.type); return this.OPS[g][0][0]; }
  defaultVal(f,op){
    const g=this.typeGroup(f.type);
    if(op==='between') return f.type==='date'?['2024-01-01','2025-01-01']:[0,10];
    if(g==='enum') return f.options[0];
    if(g==='bool') return null;
    if(g==='number') return f.type==='duration'?2:(f.key==='year_released'?2018:10);
    if(g==='date') return '2025-01-01';
    if(g==='date_nullable') return '2025-01-01';
    if(op==='empty'||op==='set'||op==='unset') return null;
    return '';
  }
  newCondition(model){ const f=this.SCHEMA[model].fields[0]; const op=this.defaultOp(f); return {id:this.uid(),kind:'condition',field:f.key,op,value:this.defaultVal(f,op)}; }
  newGroup(con){ return {id:this.uid(),kind:'group',connective:con||'AND',children:[]}; }

  // ---- default trees ----
  cond(model,field,op,value){ return {id:this.uid(),kind:'condition',field,op,value}; }
  rel(model,key,quant,child){ const r=this.relation(model,key); return {id:this.uid(),kind:'relation',relation:key,quantifier:r.many?(quant||'ANY'):null,count:{op:'gte',n:3},child}; }

  defaultTreeFor(model){
    if(model==='Game'){
      return {id:this.uid(),kind:'group',connective:'AND',children:[
        this.cond('Game','status','eq','Finished'),
        {id:this.uid(),kind:'group',connective:'OR',children:[
          this.cond('Game','playtime','gte',20),
          this.rel('Game','sessions','ANY',{id:this.uid(),kind:'group',connective:'AND',children:[
            this.cond('Session','duration_total','gte',2),
            this.rel('Session','device',null,{id:this.uid(),kind:'group',connective:'AND',children:[
              this.cond('Device','type','eq','Handheld'),
            ]}),
          ]}),
        ]},
        {id:this.uid(),kind:'group',connective:'NOT',children:[
          this.rel('Game','purchases','ANY',{id:this.uid(),kind:'group',connective:'AND',children:[
            this.cond('Purchase','ownership_type','eq','Trial'),
          ]}),
        ]},
      ]};
    }
    if(model==='Session'){
      return {id:this.uid(),kind:'group',connective:'AND',children:[
        this.cond('Session','duration_total','gte',2),
        this.rel('Session','game',null,{id:this.uid(),kind:'group',connective:'AND',children:[
          this.cond('Game','status','eq','Finished'),
        ]}),
      ]};
    }
    if(model==='Purchase'){
      return {id:this.uid(),kind:'group',connective:'AND',children:[
        this.cond('Purchase','price','gte',60),
        this.cond('Purchase','ownership_type','eq','Physical'),
      ]};
    }
    if(model==='PlayEvent'){
      return {id:this.uid(),kind:'group',connective:'AND',children:[
        this.cond('PlayEvent','days_to_finish','lte',7),
        this.rel('PlayEvent','game',null,{id:this.uid(),kind:'group',connective:'AND',children:[
          this.cond('Game','status','eq','Finished'),
        ]}),
      ]};
    }
    if(model==='Device'){
      return {id:this.uid(),kind:'group',connective:'AND',children:[
        this.cond('Device','type','eq','Handheld'),
        this.rel('Device','sessions','COUNT',{id:this.uid(),kind:'group',connective:'AND',children:[
          this.cond('Session','duration_total','gte',1),
        ]}),
      ]};
    }
    return this.newGroup('AND');
  }

  componentWillMount(){ if(!this.state.tree) this.state.tree = this.defaultTreeFor(this.state.rootModel); }

  // ---- tree ops ----
  mapNode(node,id,fn){
    if(node.id===id) return fn(node);
    if(node.kind==='group') return {...node,children:node.children.map(c=>this.mapNode(c,id,fn))};
    if(node.kind==='relation') return {...node,child:this.mapNode(node.child,id,fn)};
    return node;
  }
  removeNode(node,id){
    if(node.kind==='group') return {...node,children:node.children.filter(c=>c.id!==id).map(c=>this.removeNode(c,id))};
    if(node.kind==='relation') return {...node,child:this.removeNode(node.child,id)};
    return node;
  }
  findNode(node,id){
    if(node.id===id) return node;
    if(node.kind==='group'){ for(const c of node.children){ const r=this.findNode(c,id); if(r) return r; } }
    if(node.kind==='relation') return this.findNode(node.child,id);
    return null;
  }
  contains(node,id){ return !!this.findNode(node,id); }

  setTree(fn){ this.setState(s=>({tree:fn(s.tree)})); }
  patch(id,p){ this.setTree(t=>this.mapNode(t,id,n=>({...n,...p}))); }
  addChild(groupId,child){ this.setTree(t=>this.mapNode(t,groupId,g=>({...g,children:[...g.children,child]}))); }
  del(id){ this.setTree(t=>this.removeNode(t,id)); }

  cycleConn(id){ this.setTree(t=>this.mapNode(t,id,g=>({...g,connective:g.connective==='AND'?'OR':g.connective==='OR'?'NOT':'AND'}))); }
  toggleConn(id){ this.setTree(t=>this.mapNode(t,id,g=>({...g,connective:g.connective==='OR'?'AND':'OR'}))); }

  addCondTo(groupId,model){ this.addChild(groupId,this.newCondition(model)); }
  addGroupTo(groupId){ this.addChild(groupId,this.newGroup('AND')); }
  addRelTo(groupId,model,relKey){
    const r=this.relation(model,relKey);
    const child={id:this.uid(),kind:'group',connective:'AND',children:[this.newCondition(r.target)]};
    this.addChild(groupId,{id:this.uid(),kind:'relation',relation:relKey,quantifier:r.many?'ANY':null,count:{op:'gte',n:3},child});
  }

  changeField(id,model,newKey){
    const f=this.field(model,newKey); const op=this.defaultOp(f);
    this.patch(id,{field:newKey,op,value:this.defaultVal(f,op)});
  }
  changeOp(id,model,field,newOp){
    const f=this.field(model,field); const old=this.findNode(this.state.tree,id);
    let value=old?old.value:null;
    if(newOp==='between'&&!Array.isArray(value)) value=this.defaultVal(f,'between');
    else if(newOp!=='between'&&Array.isArray(value)) value=this.defaultVal(f,newOp);
    else if(['empty','set','unset','true','false'].includes(newOp)) value=null;
    else if(value==null) value=this.defaultVal(f,newOp);
    this.patch(id,{op:newOp,value});
  }

  // ---- drag / reparent ----
  onDragStart(e,id){ e.stopPropagation(); this.setState({dragId:id}); try{e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',id);}catch(_){} }
  canDrop(groupId){ const d=this.state.dragId; if(!d||d===groupId) return false; const node=this.findNode(this.state.tree,d); if(node&&this.contains(node,groupId)) return false; return true; }
  onDragOver(e,groupId){ if(!this.canDrop(groupId)) return; e.preventDefault(); e.stopPropagation(); if(this.state.dropId!==groupId) this.setState({dropId:groupId}); }
  onDrop(e,groupId){ if(!this.canDrop(groupId)) return; e.preventDefault(); e.stopPropagation();
    const d=this.state.dragId;
    this.setTree(t=>{ const node=this.findNode(t,d); if(!node) return t; let nt=this.removeNode(t,d); nt=this.mapNode(nt,groupId,g=>({...g,children:[...g.children,node]})); return nt; });
    this.setState({dragId:null,dropId:null});
  }
  onDragEnd(){ this.setState({dragId:null,dropId:null}); }

  switchRoot(key){ this.setState({rootModel:key,tree:this.defaultTreeFor(key),dragId:null,dropId:null}); }

  // ---- selectivity / counts ----
  hash(s){ let h=2166136261; s=String(s); for(let i=0;i<s.length;i++){ h^=s.charCodeAt(i); h=Math.imul(h,16777619);} return h>>>0; }
  condSel(c){ const h=this.hash(c.field+'|'+c.op+'|'+JSON.stringify(c.value)); return 0.18+(h%1000)/1000*0.62; }
  sel(node,model){
    if(node.kind==='condition') return this.condSel(node);
    if(node.kind==='group'){
      if(!node.children.length) return 1;
      const cs=node.children.map(c=>this.sel(c,model));
      if(node.connective==='OR') return 1-cs.reduce((a,b)=>a*(1-b),1);
      const andS=cs.reduce((a,b)=>a*b,1);
      return node.connective==='NOT'?(1-andS):andS;
    }
    if(node.kind==='relation'){
      const r=this.relation(model,node.relation); const tgt=r?r.target:model;
      const cs=this.sel(node.child,tgt);
      if(!r||!r.many) return cs;
      const k=4;
      if(node.quantifier==='ALL') return Math.pow(cs,k);
      if(node.quantifier==='NONE') return Math.pow(1-cs,k);
      if(node.quantifier==='COUNT') return Math.min(0.92,Math.max(0.04,cs*0.8));
      return 1-Math.pow(1-cs,k);
    }
    return 1;
  }
  count(node,model){ return Math.round(this.BASE[model]*this.sel(node,model)); }
  fmt(n){ return n.toLocaleString('en-US'); }

  // ---- natural language ----
  opWord(op){ const m={contains:'contains',eq:'is',neq:'is not',starts:'starts with',gte:'≥',lte:'≤',gt:'>',lt:'<',between:'between',after:'after',before:'before',on:'on',lastdays:'in last'}; return m[op]||op; }
  valWord(c,f){
    if(c.op==='between'&&Array.isArray(c.value)) return c.value[0]+'–'+c.value[1];
    if(c.op==='lastdays') return c.value+' days';
    let v=c.value; if(f.type==='duration') v=v+'h'; if(f.type==='price'||f.key==='price') v='$'+v; return v;
  }
  describeCond(c,model){ const f=this.field(model,c.field); const L=f.label.toLowerCase();
    if(c.op==='empty') return L+' is empty';
    if(c.op==='set') return L+' is set'; if(c.op==='unset') return L+' is not set';
    if(c.op==='true') return L+' is true'; if(c.op==='false') return L+' is false';
    return L+' '+this.opWord(c.op)+' '+this.valWord(c,f);
  }
  strip(s){ return s.replace(/^\((.*)\)$/,'$1'); }
  describe(node,model){
    if(node.kind==='condition') return this.describeCond(node,model);
    if(node.kind==='group'){
      if(!node.children.length) return '∅';
      const parts=node.children.map(c=>this.describe(c,model));
      if(node.connective==='NOT') return 'not '+(parts.length>1?'('+parts.join(' and ')+')':parts[0]);
      const j=node.connective==='OR'?' or ':' and ';
      return parts.length>1?'('+parts.join(j)+')':parts[0];
    }
    if(node.kind==='relation'){
      const r=this.relation(model,node.relation); const inner=this.strip(this.describe(node.child,r.target));
      if(!r.many) return r.label.toLowerCase()+' '+inner;
      const q=node.quantifier; const ql=r.label.toLowerCase();
      const qt = q==='ANY'?'any '+ql : q==='ALL'?'every '+ql : q==='NONE'?'no '+ql : (this.COUNT_OPS.find(o=>o[0]===node.count.op)[1])+node.count.n+' '+ql;
      return qt+' where '+inner;
    }
    return '';
  }

  // ---- styles ----
  get compact(){ return (this.props.density||'comfortable')==='compact'; }
  conColor(c){ return c==='OR'?this.C.OR:c==='NOT'?this.C.NOT:this.C.AND; }
  conLabel(c){ return c; }
  shade(hex){ return hex+'';
  }
  selStyle(){ const cz=this.compact; return {background:this.C.input,color:this.C.text,border:'1px solid '+this.C.border,borderRadius:8,padding:cz?'4px 6px':'6px 9px',fontSize:13,fontFamily:"'Space Mono',monospace"}; }
  inStyle(w){ const cz=this.compact; return {background:this.C.input,color:this.C.text,border:'1px solid '+this.C.border,borderRadius:8,padding:cz?'4px 7px':'6px 9px',fontSize:13,fontFamily:"'Space Mono',monospace",width:w||74}; }
  iconBtn(){ return {background:'transparent',color:this.C.muted,border:'1px solid '+this.C.border,borderRadius:7,padding:'3px 9px',fontSize:12.5,fontWeight:500,lineHeight:1.4}; }

  // ---- value editor ----
  renderValue(node,model){
    const h=this.H; const f=this.field(model,node.field); const g=this.typeGroup(f.type); const op=node.op;
    if(['empty','set','unset','true','false'].includes(op)) return null;
    const set=v=>this.patch(node.id,{value:v});
    if(g==='enum') return h('select',{value:node.value,onChange:e=>set(e.target.value),style:this.selStyle()}, f.options.map(o=>h('option',{key:o,value:o},o)));
    if(op==='between'){
      const v=Array.isArray(node.value)?node.value:[0,0]; const isDate=g==='date'||g==='date_nullable';
      return h('span',{style:{display:'inline-flex',gap:6,alignItems:'center'}},[
        h('input',{key:'a',type:isDate?'date':'number',value:v[0],onChange:e=>set([e.target.value,v[1]]),style:this.inStyle(isDate?130:64)}),
        h('span',{key:'d',style:{color:this.C.faint,fontSize:12}},'and'),
        h('input',{key:'b',type:isDate?'date':'number',value:v[1],onChange:e=>set([v[0],e.target.value]),style:this.inStyle(isDate?130:64)}),
      ]);
    }
    if(op==='lastdays') return h('input',{type:'number',value:node.value,onChange:e=>set(e.target.value),style:this.inStyle(64)});
    if(g==='number'){ const suffix=f.type==='duration'?'h':null; return h('span',{style:{display:'inline-flex',gap:5,alignItems:'center'}},[h('input',{key:'n',type:'number',value:node.value,onChange:e=>set(e.target.value),style:this.inStyle(72)}),suffix?h('span',{key:'s',style:{color:this.C.faint,fontSize:12}},suffix):null]); }
    if(g==='date'||g==='date_nullable') return h('input',{type:'date',value:node.value,onChange:e=>set(e.target.value),style:this.inStyle(140)});
    return h('input',{type:'text',value:node.value,placeholder:'value…',onChange:e=>set(e.target.value),style:this.inStyle(150)});
  }

  // ---- condition row ----
  renderCondition(node,model){
    const h=this.H; const f=this.field(model,node.field); const g=this.typeGroup(f.type);
    const dragging=this.state.dragId===node.id;
    return h('div',{key:node.id, draggable:true, onDragStart:e=>this.onDragStart(e,node.id), onDragEnd:()=>this.onDragEnd(),
      style:{display:'flex',alignItems:'center',gap:8,flexWrap:'wrap',background:'#13151e',border:'1px solid '+this.C.border,borderRadius:10,padding:this.compact?'6px 9px':'8px 11px',opacity:dragging?.4:1,animation:'pop .12s ease'}},[
      h('span',{key:'h',title:'drag to re-parent',style:{cursor:'grab',color:this.C.faint,fontSize:14,userSelect:'none'}},'⠿'),
      h('select',{key:'f',value:node.field,onChange:e=>this.changeField(node.id,model,e.target.value),style:{...this.selStyle(),color:this.C.text,fontWeight:600}}, this.SCHEMA[model].fields.map(x=>h('option',{key:x.key,value:x.key},x.label))),
      h('select',{key:'o',value:node.op,onChange:e=>this.changeOp(node.id,model,node.field,e.target.value),style:{...this.selStyle(),color:this.C.muted}}, this.OPS[g].map(o=>h('option',{key:o[0],value:o[0]},o[1]))),
      this.renderValue(node,model),
      h('span',{key:'sp',style:{flex:1}}),
      h('button',{key:'x',onClick:()=>this.del(node.id),title:'remove',style:{...this.iconBtn(),color:this.C.faint,padding:'3px 8px'}},'✕'),
    ]);
  }

  // ---- relation-descent node ----
  renderRelation(node,model,depth){
    const h=this.H; const r=this.relation(model,node.relation); const tgt=r.target; const dragging=this.state.dragId===node.id;
    const cnt=this.props.showMatchCounts!==false?this.count(node,model):null;
    const head=[];
    head.push(h('span',{key:'p',style:{fontFamily:"'Space Mono',monospace",fontWeight:700,fontSize:11,letterSpacing:'.06em',color:'#0f1018',background:this.C.REL,borderRadius:7,padding:'3px 9px'}},'↳ INTO'));
    if(r.many){
      head.push(h('select',{key:'q',value:node.quantifier,onChange:e=>this.patch(node.id,{quantifier:e.target.value}),style:{...this.selStyle(),color:this.C.REL,fontWeight:700,borderColor:this.C.REL+'66'}},[
        h('option',{key:1,value:'ANY'},'ANY'),h('option',{key:2,value:'ALL'},'ALL'),h('option',{key:3,value:'NONE'},'NONE'),h('option',{key:4,value:'COUNT'},'COUNT'),
      ]));
      if(node.quantifier==='COUNT'){
        head.push(h('select',{key:'cop',value:node.count.op,onChange:e=>this.patch(node.id,{count:{...node.count,op:e.target.value}}),style:this.selStyle()}, this.COUNT_OPS.map(o=>h('option',{key:o[0],value:o[0]},o[1]))));
        head.push(h('input',{key:'cn',type:'number',value:node.count.n,onChange:e=>this.patch(node.id,{count:{...node.count,n:e.target.value}}),style:this.inStyle(52)}));
      }
      head.push(h('span',{key:'of',style:{color:this.C.muted,fontSize:13}},'of'));
    } else {
      head.push(h('span',{key:'wh',style:{color:this.C.muted,fontSize:13}},'the'));
    }
    head.push(h('span',{key:'rl',style:{fontWeight:600,fontSize:14,color:this.C.text}},r.label));
    head.push(h('span',{key:'tg',style:{fontFamily:"'Space Mono',monospace",fontSize:10.5,color:this.C.faint,border:'1px solid '+this.C.border,borderRadius:20,padding:'1px 8px'}},tgt));
    head.push(h('span',{key:'wr',style:{color:this.C.faint,fontSize:13}}, r.many?'where':'where'));
    head.push(h('span',{key:'sp',style:{flex:1}}));
    if(cnt!=null) head.push(h('span',{key:'ct',style:{fontFamily:"'Space Mono',monospace",fontSize:11.5,color:this.C.REL,background:this.C.REL+'14',border:'1px solid '+this.C.REL+'33',borderRadius:20,padding:'2px 9px'}},'≈ '+this.fmt(cnt)));
    head.push(h('button',{key:'x',onClick:()=>this.del(node.id),title:'remove',style:{...this.iconBtn(),color:this.C.faint}},'✕'));

    return h('div',{key:node.id, draggable:true, onDragStart:e=>this.onDragStart(e,node.id), onDragEnd:()=>this.onDragEnd(),
      style:{background:'#171a28',border:'1px solid '+this.C.REL+'33',borderLeft:'3px solid '+this.C.REL,borderRadius:12,padding:this.compact?'9px 11px':'11px 13px',opacity:dragging?.4:1,animation:'pop .12s ease'}},[
      h('div',{key:'hd',style:{display:'flex',alignItems:'center',gap:9,flexWrap:'wrap'}},head),
      h('div',{key:'bd',style:{marginTop:10}}, this.renderGroup(node.child,tgt,depth+1,{fixed:true})),
    ]);
  }

  // ---- group ----
  renderChip(group){
    const h=this.H; const c=group.connective; const col=this.conColor(c); const lab=c==='NOT'?'AND':c;
    return h('button',{key:'chip'+Math.random(), onClick:()=>this.toggleConn(group.id), title:'toggle AND / OR',
      style:{alignSelf:'flex-start',marginLeft:-7,fontFamily:"'Space Mono',monospace",fontSize:10,fontWeight:700,letterSpacing:'.06em',color:col,background:col+'1a',border:'1px solid '+col+'4d',borderRadius:6,padding:'1px 7px'}},lab);
  }

  renderGroup(group,model,depth,opts){
    opts=opts||{}; const h=this.H; const con=group.connective; const col=this.conColor(con);
    const isDrop=this.state.dropId===group.id;
    const cnt=this.props.showMatchCounts!==false?this.count(group,model):null;
    const bg=depth%2===0?this.C.panel:this.C.panel2;
    const dragging=this.state.dragId===group.id;

    // header
    const subtext = con==='AND'?'match all':con==='OR'?'match any':'exclude all';
    const head=h('div',{key:'h',style:{display:'flex',alignItems:'center',gap:10,flexWrap:'wrap'}},[
      h('button',{key:'pill',onClick:()=>this.cycleConn(group.id),title:'cycle AND → OR → NOT',
        style:{fontFamily:"'Space Mono',monospace",fontWeight:700,fontSize:12,letterSpacing:'.08em',color:'#0f1018',background:col,border:'none',borderRadius:7,padding:'4px 11px',boxShadow:'0 2px 0 rgba(0,0,0,.35)'}}, con),
      h('span',{key:'st',style:{fontSize:12.5,color:this.C.muted}},subtext),
      cnt!=null?h('span',{key:'ct',style:{fontFamily:"'Space Mono',monospace",fontSize:11.5,color:this.C.muted,background:'#0000003a',border:'1px solid '+this.C.border,borderRadius:20,padding:'2px 9px'}},'≈ '+this.fmt(cnt)+' '+this.SCHEMA[model].plural.toLowerCase()):null,
      h('span',{key:'sp',style:{flex:1}}),
      // toolbar
      h('div',{key:'tb',style:{display:'flex',gap:6,alignItems:'center',flexWrap:'wrap'}},[
        h('button',{key:'ac',onClick:()=>this.addCondTo(group.id,model),style:this.iconBtn()},'+ condition'),
        h('button',{key:'ag',onClick:()=>this.addGroupTo(group.id),style:this.iconBtn()},'+ group'),
        this.SCHEMA[model].relations.length?h('select',{key:'ar',value:'',onChange:e=>{ if(e.target.value){ this.addRelTo(group.id,model,e.target.value);} e.target.value=''; },
          style:{...this.iconBtn(),color:this.C.REL,borderColor:this.C.REL+'40',background:this.C.REL+'12'}},[
          h('option',{key:0,value:''},'+ relation ↳'),
          ...this.SCHEMA[model].relations.map(r=>h('option',{key:r.key,value:r.key},r.label+(r.many?' (many)':' (one)'))),
        ]):null,
        (!opts.fixed)?h('button',{key:'x',onClick:()=>this.del(group.id),title:'remove group',style:{...this.iconBtn(),color:this.C.faint}},'✕'):null,
      ]),
    ]);

    // children
    const kids=[];
    group.children.forEach((c,i)=>{
      if(i>0) kids.push(this.renderChip(group));
      kids.push(this.renderNode(c,model,depth));
    });
    if(!group.children.length){
      kids.push(h('div',{key:'empty',style:{color:this.C.faint,fontSize:12.5,fontStyle:'italic',padding:'8px 4px'}},'Empty group — add a condition, sub-group, or relation, or drop a row here.'));
    }
    const body=h('div',{key:'b',style:{marginTop:11,marginLeft:7,paddingLeft:14,borderLeft:'1px dashed '+col+'55',display:'flex',flexDirection:'column',gap:this.compact?7:9}},kids);

    return h('div',{key:group.id, draggable:!opts.fixed, onDragStart:e=>!opts.fixed&&this.onDragStart(e,group.id), onDragEnd:()=>this.onDragEnd(),
      onDragOver:e=>this.onDragOver(e,group.id), onDrop:e=>this.onDrop(e,group.id),
      style:{background:bg,border:'1px solid '+(isDrop?col:this.C.border),borderLeft:'3px solid '+col,borderRadius:13,padding:this.compact?'11px 12px':'13px 14px',opacity:dragging?.45:1,boxShadow:isDrop?'0 0 0 2px '+col+'55 inset':'none',transition:'box-shadow .1s',animation:'pop .12s ease'}},[head,body]);
  }

  renderNode(node,model,depth){
    if(node.kind==='group') return this.renderGroup(node,model,depth+1);
    if(node.kind==='relation') return this.renderRelation(node,model,depth);
    return this.renderCondition(node,model);
  }

  renderVals(){
    const m=this.state.rootModel; const sc=this.SCHEMA[m];
    const rootOptions=this.ROOTS.map(k=>{
      const s=this.SCHEMA[k]; const active=k===m;
      return { key:k, label:s.plural, onClick:()=>this.switchRoot(k),
        style:{display:'flex',alignItems:'center',gap:7,background:active?'#222a3d':'transparent',color:active?this.C.text:this.C.muted,border:'1px solid '+(active?'#3a4663':this.C.border),borderRadius:9,padding:'6px 12px',fontSize:13,fontWeight:active?600:500} };
    });

    return {
      rootOptions,
      rootLabelLower: sc.plural.toLowerCase(),
      matchCount: this.fmt(this.count(this.state.tree,m)),
      rootCount: this.fmt(this.BASE[m]),
      showReadout: this.props.naturalLanguage!==false,
      readout: sc.plural+' where '+this.strip(this.describe(this.state.tree,m))+'.',
      tree: this.renderGroup(this.state.tree,m,0,{fixed:true}),
      onReset: ()=>this.setState({tree:this.defaultTreeFor(this.state.rootModel),dragId:null,dropId:null}),
    };
  }
}