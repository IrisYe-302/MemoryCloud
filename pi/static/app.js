const $ = id => document.getElementById(id);
let state = {photos:[],printers:[],jobs:[]}, selected = null, previewURL, timer, generation = 0, sending = false, lastState = '';
let captionPhoto=null,captionAlbum=null,captionVersion=0,captionBusy=false,captionRequested=false;
let duplicateVersion=0,duplicateScanning=false;
let contributorFilter=new Set();
let colorPhoto=null,colorURL=null,colorGeneration=0,colorTimer,colorSaving=false;
let account=null, registering=false, setupRequired=false, refreshVersion=0;
let suggestionPrinter=null, suggesting=false, suggestionVersion=0;
const seenSuggestions=new Map();
function cancelSuggestion(){suggestionVersion++;suggestionPrinter=null;$('suggestionReview').hidden=true;$('suggestionPhoto').removeAttribute('src');$('send').textContent='Send to selected printers ↗';}
let invitation = new URLSearchParams(location.hash.slice(1)).get('invite') || '';
if(invitation) history.replaceState(null,'',location.pathname);
const notice = text => { $('notice').textContent = text; };
async function api(url, body, method='POST') {
  const response = await fetch(url, {method, headers:{'X-Memory-Client':'web', ...(account?{'X-Memory-Album':account.selected}:{}), ...(body === undefined || body instanceof FormData ? {} : {'Content-Type':'application/json'})}, body: body instanceof FormData ? body : JSON.stringify(body)});
  if (!response.ok) { let error; try {error = (await response.json()).error;} catch {} throw Error(error || `Request failed (${response.status})`); }
  return response;
}
function options() { return {brightness:Number($('brightness').value),threshold:Number($('threshold').value),auto_levels:$('autoLevels').checked,aspect:$('aspect').value,zoom:Number($('zoom').value),crop_x:Number($('cropX').value),crop_y:Number($('cropY').value),frame:$('frame').value, caption:$('caption').value, mode:$('mode').value, width:Number($('width').value), contrast:Number($('contrast').value)}; }
function element(tag, text, cls) { const el = document.createElement(tag); if(text !== undefined) el.textContent=text; if(cls) el.className=cls; return el; }
function draw() {
  syncCaptionSuggestions();
  const connectedPrinters=state.printers.filter(p=>p.physical);
  $('findDuplicates').disabled=duplicateScanning||state.photos.length<2;
  if(colorPhoto!==selected){colorPhoto=selected;resetColor();}
  $('removePhoto').disabled=!selected||sending;
  $('reprint').disabled=!!suggestionPrinter;
  const priorPrinter=$('surprisePrinter').value;
  $('surprisePrinter').replaceChildren(...connectedPrinters.map(p=>{const opt=element('option',p.name);opt.value=p.id;return opt;}));
  if(state.printers.some(p=>p.id===priorPrinter))$('surprisePrinter').value=priorPrinter;
  $('surprise').disabled=suggesting||!state.photos.length||!connectedPrinters.length;
  const heroPhotos = ['IMG_7230.JPG', '18988.JPG'].map((name,index)=>
    state.photos.find(photo=>photo.name===name) || state.photos[index] || state.photos[0]);
  ['heroBack','heroFront'].forEach((id,index)=>{
    const img=$(id), photo=heroPhotos[index];
    if(photo) img.src='/api/photos/'+photo.id+'?album='+encodeURIComponent(account.selected);
    else img.removeAttribute('src');
    img.hidden=!photo;
  });
  $('count').textContent = `${state.photos.length} ${state.photos.length===1?'memory':'memories'}`;
  $('empty').hidden=state.photos.length>0;
  const visiblePhotos=state.photos.filter(p=>!contributorFilter.size||contributorFilter.has(p.contributor_id||'legacy'));
  $('archiveFilterEmpty').hidden=!state.photos.length||visiblePhotos.length>0;
  $('count').textContent=contributorFilter.size?`${visiblePhotos.length} of ${state.photos.length} memories`:`${state.photos.length} ${state.photos.length===1?'memory':'memories'}`;
  const sortedPhotos=[...visiblePhotos].sort((a,b)=>{const direction=$('photoSort').value;if(direction==='contributor'){const names=(a.contributor||'Iris').localeCompare(b.contributor||'Iris');if(names)return names;}return (direction==='oldest'?1:-1)*((a.added??a.created)-(b.added??b.created))||a.id.localeCompare(b.id);});
  $('gallery').replaceChildren(...sortedPhotos.map((p,index) => {
    const b=element('button',undefined,'photo'+(p.id===selected?' selected':''));
    const img=document.createElement('img'); img.src='/api/photos/'+p.id+'?album='+encodeURIComponent(account.selected); img.alt=`Memory ${index+1}`; img.loading='lazy';
    b.append(img,element('span',('Added by '+(p.contributor||'Iris'))+(p.original?' · edited copy':''),'contributor-tag')); b.onclick=()=>{cancelSuggestion();selected=p.id;resetCrop();$('editor').disabled=false;draw();updatePreview();};return b;
  }));
  const checked = new Set([...$('targets').querySelectorAll('input:checked')].map(i=>i.value));
  const first = !$('targets').children.length;
  $('targets').replaceChildren(...connectedPrinters.map(p=>{
    const label=element('label',undefined,'check'), check=document.createElement('input');check.type='checkbox';check.value=p.id;check.checked=checked.has(p.id)||(first&&p.id===(connectedPrinters.find(item=>item.owner===account?.user.id)||connectedPrinters[0])?.id);label.append(check,document.createTextNode(`${p.name} · ${p.online?'online':'offline'}`));return label;
  }));
  drawPrinters();
  $('printerNeeded').hidden=connectedPrinters.length>0;
  if(suggestionPrinter)for(const input of $('targets').querySelectorAll('input')){input.checked=input.value===suggestionPrinter;input.disabled=true;}
  $('historyEmpty').hidden=state.jobs.some(isPhysicalJob);
  $('jobs').replaceChildren(...state.jobs.filter(isPhysicalJob).map(j=>{
    const row=element('div',undefined,'job'), img=document.createElement('img');img.src='/static/polaroid.svg';img.alt='';
    const name=state.printers.find(p=>p.id===j.printer)?.name || 'Deleted printer';
    const link=element('a','View print');link.href='/api/prints/'+j.id+'?album='+encodeURIComponent(account.selected);link.target='_blank';link.rel='noopener';
    row.append(img,element('span',name),element('em',j.state),link);if(j.state==='uncertain'&&state.printers.find(p=>p.id===j.printer)?.owner===account?.user.id){for(const [text,value] of [['It printed','printed'],['It did not print','failed']]){const resolve=element('button',text);resolve.onclick=async()=>{try{await api('/api/jobs/'+j.id+'/resolve',{state:value});await refresh();}catch(e){notice(e.message);}};row.append(resolve);}}return row;
  }));
}
async function refresh(){const version=refreshVersion;const r=await fetch('/api/state',{headers:account?{'X-Memory-Album':account.selected}:{}});if(version!==refreshVersion)return;if(r.status===401){await showAuth();return;}if(!r.ok)throw Error('Unable to load album');const next=await r.json();if(version!==refreshVersion)return;const packed=JSON.stringify(next);if(packed===lastState)return;lastState=packed;state=next;draw();}
async function updatePreview(){
  if(!selected)return; const seq=++generation;$('send').disabled=true;$('preview').hidden=true;$('previewEmpty').hidden=false;
  try{const response=await api('/api/preview/'+selected,options());const blob=await response.blob();if(seq!==generation)return;
    if(previewURL)URL.revokeObjectURL(previewURL);previewURL=URL.createObjectURL(blob);$('preview').src=previewURL;$('preview').hidden=false;$('previewEmpty').hidden=true;$('download').href=previewURL;$('send').disabled=false;
  }catch(e){notice(e.message);}
}
for(const id of ['frame','caption','mode','width','contrast','aspect','zoom','cropX','cropY','brightness','threshold','autoLevels'])$(id).addEventListener('input',event=>{if(event.isComposing)return;updateRenderingControls();$('contrastValue').value=$('contrast').value;$('zoomValue').value=$('zoom').value+'×';generation++;$('send').disabled=true;clearTimeout(timer);timer=setTimeout(updatePreview,180);});
$('upload').onchange=$('albumUpload').onchange=async e=>{cancelSuggestion();try{notice('Saving your memories…');for(const file of e.target.files){const form=new FormData();form.append('photo',file);const r=await api('/api/photos',form);selected=(await r.json()).id;resetCrop();}$('editor').disabled=!selected;await refresh();await updatePreview();notice('Saved to your album. Choose a frame and send it.');}catch(err){notice(err.message);}finally{e.target.value='';}};
$('send').onclick=async()=>{
  if(sending||suggesting)return; sending=true;$('send').disabled=true;
  try{const printers=[...$('targets').querySelectorAll('input:checked')].map(i=>i.value);if(!printers.length)throw Error('Choose at least one printer.');
    const key=Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
    const r=await api('/api/jobs',{key,photo:selected,printers,queue:$('policy').value==='yes',reprint:suggestionPrinter?false:$('reprint').checked,options:options()});const result=await r.json();notice(result.results.map(j=>j.error?`${j.printer}: ${j.error}`:`Sent to ${j.printer}.`).join(' '));if(suggestionPrinter&&result.results.every(j=>!j.error)){cancelSuggestion();selected=null;$('editor').disabled=true;}await refresh();draw();
  }catch(e){notice(e.message);}finally{sending=false;$('send').disabled=false;}
};
async function suggestMemory(){
  if(suggesting||sending)return;
  const printer=$('surprisePrinter').value, album=account?.selected;
  if(!printer)return notice('Add a printer first.');
  const session=album+':'+printer, seen=seenSuggestions.get(session)||[];
  if(seen.length>=2000)return notice('Suggestion session complete. Reload to start again.');
  const version=++suggestionVersion;suggesting=true;$('surprise').disabled=true;$('tryAnother').disabled=true;
  try{
    const r=await api('/api/suggestions',{printer,seen});const {photo}=await r.json();
    if(version!==suggestionVersion||album!==account?.selected)return;
    if(!photo){notice('No more unprinted memories to suggest for this printer. Try another album or printer.');return;}
    seenSuggestions.set(session,[...seen,photo.id]);suggestionPrinter=printer;selected=photo.id;resetCrop();
    $('suggestionPhoto').src='/api/photos/'+photo.id+'?album='+encodeURIComponent(album);$('suggestionReview').hidden=false;
    $('suggestionMessage').textContent='Like this one? Adjust its frame and caption, then approve it in the print studio.';
    $('caption').value='';$('reprint').checked=false;$('editor').disabled=false;$('send').textContent='Approve & add to print queue ↗';
    draw();await updatePreview();notice('Suggestion ready. Nothing has been queued.');
  }catch(e){if(version===suggestionVersion)notice(e.message);}finally{suggesting=false;$('tryAnother').disabled=false;draw();}
}
$('surprise').onclick=suggestMemory;$('tryAnother').onclick=suggestMemory;
$('cancelSuggestion').onclick=()=>{cancelSuggestion();selected=null;generation++;$('editor').disabled=true;$('preview').hidden=true;$('previewEmpty').hidden=false;draw();notice('Suggestion dismissed. Nothing was queued.');};
$('surprisePrinter').onchange=()=>{$('cancelSuggestion').click();};
function clearAlbum(){contributorFilter.clear();duplicateVersion++;duplicateScanning=false;$('duplicateReview').hidden=true;$('duplicateGroups').replaceChildren();cancelSuggestion();seenSuggestions.clear();refreshVersion++;generation++;clearTimeout(timer);selected=null;lastState='';state={photos:[],printers:[],jobs:[]};$('editor').disabled=true;$('preview').hidden=true;$('preview').removeAttribute('src');$('previewEmpty').hidden=false;$('download').removeAttribute('href');if(previewURL)URL.revokeObjectURL(previewURL);previewURL=null;$('caption').value='';$('reprint').checked=false;$('inviteResult').hidden=true;$('inviteLink').value='';$('inviteExpiry').textContent='';draw();}
async function showAuth(){account=null;clearAlbum();document.body.classList.add('signed-out');$('authPanel').hidden=false;$('accountPanel').hidden=true;const r=await fetch('/api/auth/status');setupRequired=(await r.json()).setup_required;registering=setupRequired||!!invitation;drawAuth();}
function drawAuth(){$('nameLabel').hidden=!registering;$('displayName').required=registering;$('setupLabel').hidden=!setupRequired;$('setupCode').required=setupRequired;$('authToggle').hidden=setupRequired;$('authSubmit').textContent=registering?'Create my account':'Sign in';$('authToggle').textContent=registering?'Already have an account? Sign in':'New here? Create an account';$('authDescription').textContent=setupRequired?'Create the first account to claim your existing album and demo printers.':registering?(invitation?'Create an account to join the album you were invited to.':'Create an account and start your own private album.'):'Sign in to your private albums.';$('password').autocomplete=registering?'new-password':'current-password';}
async function loadAccount(){const r=await fetch('/api/account');if(r.status===401){await showAuth();return;}if(!r.ok)throw Error('Unable to load account');account=await r.json();document.body.classList.remove('signed-out');$('authPanel').hidden=true;$('accountPanel').hidden=false;$('accountName').textContent=`Hello, ${account.user.name||account.user.username}.`;$('albumSelect').replaceChildren(...account.albums.map(a=>{const opt=element('option',a.name);opt.value=a.id;return opt;}));$('albumSelect').value=account.selected;$('memberList').textContent='Together with: '+account.members.map(m=>m.name||m.username).join(', ');$('inviteControls').hidden=account.albums.find(a=>a.id===account.selected)?.owner!==account.user.id;$('pendingInvite').hidden=!invitation;await refresh();}
$('authToggle').onclick=()=>{registering=!registering;$('authNotice').textContent='';drawAuth();};
$('authForm').onsubmit=async e=>{e.preventDefault();$('authSubmit').disabled=true;try{await api(registering?'/api/auth/register':'/api/auth/login',{name:registering?$('displayName').value:undefined,username:$('username').value,password:$('password').value,setup_code:$('setupCode').value,invite:invitation});if(registering)invitation='';$('password').value='';$('setupCode').value='';$('authNotice').textContent='';clearAlbum();await loadAccount();}catch(err){$('authNotice').textContent=err.message;}finally{$('authSubmit').disabled=false;}};
$('logout').onclick=async()=>{try{await api('/api/auth/logout',{});await showAuth();notice('');}catch(e){notice(e.message);}};
$('albumSelect').onchange=async()=>{try{await api('/api/albums/select',{album:$('albumSelect').value});clearAlbum();await loadAccount();notice('Album switched.');}catch(e){notice(e.message);}};
$('newAlbumForm').onsubmit=async e=>{e.preventDefault();try{const r=await api('/api/albums',{name:$('albumName').value});await api('/api/albums/select',{album:(await r.json()).id});$('albumName').value='';clearAlbum();await loadAccount();notice('Your new album is ready.');}catch(err){notice(err.message);}};
$('newPrinterForm').onsubmit=async e=>{e.preventDefault();try{await api('/api/printers',{name:$('printerName').value});$('printerName').value='';await refresh();notice('Printer added. Open its setup to connect your ESP.');}catch(err){notice(err.message);}};
$('makeInvite').onclick=async()=>{try{const r=await api('/api/invites',{hours:Number($('inviteHours').value)});const result=await r.json();$('inviteLink').value=location.origin+'/#invite='+encodeURIComponent(result.token);$('inviteResult').hidden=false;$('inviteExpiry').textContent='One use · expires '+new Date(result.expires*1000).toLocaleString()+'. Use your server’s reachable HTTPS address when sharing with another device.';}catch(e){notice(e.message);}};
$('inviteLink').onclick=()=>{$('inviteLink').select();};
$('revokeInvites').onclick=async()=>{try{await api('/api/invites/revoke',{});$('inviteResult').hidden=true;$('inviteLink').value='';$('inviteExpiry').textContent='Unused invitation links have been revoked.';}catch(e){notice(e.message);}};
$('acceptInvite').onclick=async()=>{try{await api('/api/invites/accept',{invite:invitation});invitation='';clearAlbum();await loadAccount();notice('You joined the album.');}catch(e){notice(e.message);}};
loadAccount().catch(e=>notice(e.message));setInterval(()=>{if(account)refresh().catch(()=>{});},3000);

$('removePhoto').onclick=async()=>{
  if(!selected||sending)return;
  if(!confirm('Remove this photo from the current album for everyone? Other albums and existing print jobs will keep their copies.'))return;
  const photo=selected,album=account.selected;$('removePhoto').disabled=true;
  try{await api('/api/photos/'+photo,{},'DELETE');if(account?.selected!==album)return;clearAlbum();await refresh();notice('Photo removed from this album.');}
  catch(e){notice(e.message);}finally{draw();}
};

function printerSharing(printer){
  const details=element('details',undefined,'printer-sharing');
  const summary=element('summary','Share printer'),form=element('form'),label=element('label','Account username');
  const input=document.createElement('input');input.required=true;input.maxLength=40;input.placeholder='Their username';input.autocomplete='off';label.append(input);
  const submit=element('button','Share'),list=element('ul'),message=element('p',undefined,'hint');message.setAttribute('role','status');
  form.append(label,submit);details.append(summary,element('p','Sharing allows this person to send photos from their albums to your printer.','hint'),form,list,message);
  async function load(){const r=await api('/api/printers/'+printer.id+'/shares',undefined,'GET');const data=await r.json();list.replaceChildren(...data.users.map(user=>{
    const li=element('li'),remove=element('button','Revoke');remove.type='button';remove.setAttribute('aria-label','Revoke printer access for '+user.username);
    remove.onclick=async()=>{remove.disabled=true;try{await api('/api/printers/'+printer.id+'/shares/'+user.id,{},'DELETE');await load();message.textContent='Access revoked. Already queued prints are unchanged.';}catch(e){message.textContent=e.message;remove.disabled=false;}};
    li.append(element('span',user.username),remove);return li;
  }));}
  details.ontoggle=()=>{if(details.open){message.textContent='';load().catch(()=>message.textContent='Could not load who has access. Close and reopen this section to retry.');}};
  form.onsubmit=async e=>{e.preventDefault();submit.disabled=true;try{await api('/api/printers/'+printer.id+'/shares',{username:input.value});input.value='';await load();message.textContent='Printer shared.';}catch(err){message.textContent=err.message;}finally{submit.disabled=false;}};
  return details;
}

function resetCrop(){$('aspect').value='original';$('zoom').value='1';$('zoomValue').value='1×';$('cropX').value='0.5';$('cropY').value='0.5';}
$('resetCrop').onclick=()=>{resetCrop();updatePreview();};

// Small decorative offsets; requestAnimationFrame batches scroll work.
const motionPreference=matchMedia('(prefers-reduced-motion: reduce)');
let parallaxFrame=0;
function updateParallax(){
  parallaxFrame=0;
  const hero=document.querySelector('.intro');
  const layers=[['.ticket-back',-12],['.ticket-front',18],['.round-stamp',-24]];
  const bounds=hero.getBoundingClientRect();
  const progress=Math.max(-1,Math.min(1,(innerHeight/2-(bounds.top+bounds.height/2))/innerHeight));
  for(const [selector,speed] of layers){
    const layer=hero.querySelector(selector);
    layer.style.translate=motionPreference.matches?'none':`0 ${(progress*speed).toFixed(2)}px`;
  }
}
function scheduleParallax(){if(!parallaxFrame)parallaxFrame=requestAnimationFrame(updateParallax);}
addEventListener('scroll',scheduleParallax,{passive:true});
addEventListener('resize',scheduleParallax,{passive:true});
motionPreference.addEventListener('change',scheduleParallax);
scheduleParallax();

function updateRenderingControls(){
  const descriptions={soft:'Soft photo lifts shadows for a lighter, gentler print.',dither:'Fine detail preserves shading with small scattered dots.',ordered:'Patterned dots use an even repeating texture for a retro print.',threshold:'A clean black-and-white cutoff. Lower the cutoff for a lighter result.'};
  $('renderHint').textContent=descriptions[$('mode').value];
  $('thresholdControl').hidden=$('mode').value!=='threshold';
  $('brightnessValue').value=$('brightness').value;
  $('thresholdValue').value=$('threshold').value;
}

$('photoSort').onchange=draw;
function colorOptions(){return {exposure:Number($('colorExposure').value),contrast:Number($('colorContrast').value),saturation:Number($('colorSaturation').value),warmth:Number($('colorWarmth').value)};}
function resetColor(){
  colorGeneration++;clearTimeout(colorTimer);
  for(const [id,value] of [['colorExposure',1],['colorContrast',1],['colorSaturation',1],['colorWarmth',0]]){$(id).value=value;$(id+'Value').value=value;}
  $('colorPreview').hidden=true;$('colorPreview').removeAttribute('src');$('colorNotice').textContent='';$('saveColor').disabled=true;
  if(colorURL)URL.revokeObjectURL(colorURL);colorURL=null;
  if(selected&&$('colorEditor').open)updateColorPreview();
}
async function updateColorPreview(){
  if(!selected)return;
  const version=++colorGeneration,pid=selected,album=account?.selected;
  $('saveColor').disabled=true;$('colorNotice').textContent='Updating color preview…';
  try{const r=await api('/api/photos/'+pid+'/color-preview',colorOptions());const blob=await r.blob();
    if(version!==colorGeneration||pid!==selected||album!==account?.selected)return;
    if(colorURL)URL.revokeObjectURL(colorURL);colorURL=URL.createObjectURL(blob);
    $('colorPreview').src=colorURL;$('colorPreview').hidden=false;$('saveColor').disabled=colorSaving;$('colorNotice').textContent='Preview only. Save a copy to use these colors in your album and prints.';
  }catch(e){if(version===colorGeneration)$('colorNotice').textContent=e.message;}
}
for(const id of ['colorExposure','colorContrast','colorSaturation','colorWarmth'])$(id).oninput=()=>{
  $(id+'Value').value=$(id).value;colorGeneration++;$('saveColor').disabled=true;clearTimeout(colorTimer);colorTimer=setTimeout(updateColorPreview,220);
};
$('colorEditor').ontoggle=()=>{if($('colorEditor').open&&selected)updateColorPreview();};
$('resetColor').onclick=resetColor;
$('saveColor').onclick=async()=>{
  if(!selected||colorSaving)return;
  colorSaving=true;$('saveColor').disabled=true;
  const pid=selected,album=account.selected;
  try{const r=await api('/api/photos/'+pid+'/color-copy',colorOptions());const result=await r.json();
    if(album!==account?.selected)return;
    if(selected===pid){cancelSuggestion();selected=result.id;resetCrop();}
    await refresh();await updatePreview();notice('Saved an edited copy to this album. Your original is unchanged.');
  }catch(e){$('colorNotice').textContent=e.message;}finally{colorSaving=false;if(colorURL)$('saveColor').disabled=false;}
};

async function scanDuplicates(){
  const version=++duplicateVersion,album=account?.selected;
  duplicateScanning=true;$('findDuplicates').disabled=true;$('duplicateReview').hidden=false;$('duplicateGroups').replaceChildren();$('duplicateNotice').textContent='Comparing photos…';
  try{const response=await api('/api/duplicates',undefined,'GET');const data=await response.json();
    if(version!==duplicateVersion||album!==account?.selected)return;
    $('duplicateNotice').textContent=data.groups.length?`${data.groups.length} possible duplicate group(s). Review before removing.`:'No duplicates found in this album.';
    $('duplicateGroups').replaceChildren(...data.groups.map((photos,index)=>duplicateGroup(photos,index,album)));
  }catch(e){if(version===duplicateVersion)$('duplicateNotice').textContent=e.message;}
  finally{if(version===duplicateVersion){duplicateScanning=false;$('findDuplicates').disabled=state.photos.length<2;}}
}
function duplicateGroup(photos,index,album){
  const group=element('form',undefined,'duplicate-group'),grid=element('div',undefined,'duplicate-grid'),status=element('p',undefined,'hint');status.setAttribute('role','status');
  let keep=photos[0].id;
  const choices=[];
  for(const [position,photo] of photos.entries()){
    const card=element('div',undefined,'duplicate-card'),img=document.createElement('img');img.src='/api/photos/'+photo.id+'?album='+encodeURIComponent(album);img.alt=`Duplicate group ${index+1}, photo ${position+1}`;img.loading='lazy';
    const keepLabel=element('label',undefined,'check'),radio=document.createElement('input');radio.type='radio';radio.name='keep-'+index;radio.checked=photo.id===keep;keepLabel.append(radio,document.createTextNode('Keep this one'));
    const removeLabel=element('label',undefined,'check'),check=document.createElement('input');check.type='checkbox';check.checked=photo.match==='exact';check.disabled=photo.id===keep;removeLabel.append(check,document.createTextNode('Remove copy'));
    choices.push({id:photo.id,radio,check});
    radio.onchange=()=>{keep=photo.id;for(const c of choices){c.check.disabled=c.id===keep;if(c.id===keep)c.check.checked=false;}};
    card.append(img,element('p',position===0?'Reference photo':photo.match==='exact'?'Exact match':'Similar — review carefully','hint'),element('p','Added by '+(photo.contributor||'Iris'),'hint'),keepLabel,removeLabel);grid.append(card);
  }
  const submit=element('button','Remove selected copies');submit.type='submit';
  group.append(element('h4',`Group ${index+1}`),grid,submit,status);
  group.onsubmit=async e=>{e.preventDefault();if(account?.selected!==album)return;
    const remove=choices.filter(c=>c.check.checked&&c.id!==keep).map(c=>c.id);
    if(!remove.length){status.textContent='Select at least one copy to remove.';return;}
    if(!confirm(`Remove ${remove.length} extra photo(s) from this album for everyone? The kept photo, other albums and existing prints remain unchanged.`))return;
    submit.disabled=true;
    try{await api('/api/duplicates/remove',{keep,remove});if(account?.selected!==album)return;clearAlbum();await refresh();notice(`Removed ${remove.length} duplicate copy/copies from this album.`);await scanDuplicates();}
    catch(err){status.textContent=err.message;submit.disabled=false;}
  };
  return group;
}
$('findDuplicates').onclick=scanDuplicates;
$('closeDuplicates').onclick=()=>{duplicateVersion++;duplicateScanning=false;$('duplicateReview').hidden=true;$('duplicateGroups').replaceChildren();$('findDuplicates').disabled=state.photos.length<2;};

function syncCaptionSuggestions(){
  if(captionPhoto===selected&&captionAlbum===account?.selected)return;
  captionPhoto=selected;captionAlbum=account?.selected;captionVersion++;captionBusy=false;captionRequested=false;
  $('suggestCaptions').textContent='Suggest captions with AI';
  $('captionSuggestions').replaceChildren();$('captionNotice').textContent='';$('suggestCaptions').disabled=!selected;
}
$('suggestCaptions').onclick=async()=>{
  if(!selected||captionBusy)return;
  const pid=selected,album=account.selected,version=++captionVersion;
  const regenerate=captionRequested;captionRequested=true;$('suggestCaptions').textContent='Suggest captions again with AI';
  captionBusy=true;$('suggestCaptions').disabled=true;$('captionNotice').textContent='Preparing caption suggestions…';
  try{
    const response=await api('/api/photos/'+pid+'/captions',{consent:true,regenerate});const data=await response.json();
    if(version!==captionVersion||pid!==selected||album!==account?.selected)return;
    $('captionSuggestions').replaceChildren(...data.captions.map(text=>{
      const button=element('button',text,'caption-choice');button.type='button';
      button.onclick=()=>{
        if(pid!==selected||album!==account?.selected)return;
        $('caption').value=text;$('caption').dispatchEvent(new Event('input',{bubbles:true}));
        $('captionNotice').textContent='Caption added. You can edit it in “A few words” before sending.';
      };return button;
    }));
    $('captionNotice').textContent=(data.cached?'Saved suggestions — no new AI request.':'Three AI suggestions. Check that they fit your memory.')+' Select one to use it.';
  }catch(e){if(version===captionVersion)$('captionNotice').textContent=e.message;}
  finally{if(version===captionVersion){captionBusy=false;$('suggestCaptions').disabled=!selected;}}
};

function printerSetup(printer){
  const controls=document.createDocumentFragment();
  const box=element('details',undefined,'printer-sharing');box.append(element('summary','Set up printer ESP'));
  const renameBox=element('details',undefined,'printer-sharing');renameBox.append(element('summary','Rename printer'));
  const deleteBox=element('details',undefined,'printer-sharing');deleteBox.append(element('summary','Delete printer'));
  const renameMessage=element('p','','hint'),deleteMessage=element('p','','hint');
  renameMessage.setAttribute('role','status');deleteMessage.setAttribute('role','status');
  const rename=element('form'),name=element('input');name.value=printer.name;name.required=true;name.maxLength=40;
  const label=element('label','Printer name');label.append(name);rename.append(label,element('button','Save name'));
  const message=element('p','', 'hint');message.setAttribute('role','status');
  rename.onsubmit=async e=>{e.preventDefault();try{await api('/api/printers/'+printer.id,{name:name.value},'PATCH');renameBox.open=false;printer.name=name.value.trim();renameBox.closest('.printer').querySelector('strong').textContent=printer.name;lastState='';await refresh();}catch(err){renameMessage.textContent=err.message;}};
  const form=element('div',undefined,'esp-guide');
  form.append(element('p','Plug your ESP into this computer. Turn on your MXW01 printer and disconnect its phone app. No IP or Bluetooth address is needed. Use open or personal Wi-Fi; enterprise Wi-Fi logins are not supported.','hint'));
  const attach=element('button','1. Connect ESP via USB');attach.type='button';
  const networks=element('select'),networkLabel=element('label','2. Choose Wi-Fi');networkLabel.append(networks);
  const password=element('input');password.type='password';password.autocomplete='off';const passwordLabel=element('label','Wi-Fi password');passwordLabel.append(password);
  const wifiScan=element('button','Refresh Wi-Fi list');wifiScan.type='button';
  const printers=element('select'),printerLabel=element('label','3. Choose nearby printer');printerLabel.append(printers);
  const scan=element('button','Find printers'),test=element('button','4. Print a small test'),save=element('button','5. Yes, it printed — save connection'),close=element('button','Disconnect USB');
  for(const button of [scan,test,save,close])button.type='button';
  const progress=element('div',undefined,'esp-guide-steps');progress.hidden=true;progress.append(networkLabel,passwordLabel,wifiScan,printerLabel,scan,test,save,close);
  form.append(attach,progress);
  attach.disabled=!('serial' in navigator);
  if(attach.disabled)form.append(element('p','USB setup needs desktop Chrome or Edge and the latest Memory Cloud ESP firmware.','hint'));
  let port,reader,writer,readLoop,waiting=null,knownPrinters=new Map(),tested=false,serialReady=false;
  async function release(){
    serialReady=false;if(waiting){waiting.reject(Error('USB disconnected'));waiting=null;}
    if(reader){await reader.cancel().catch(()=>{});if(readLoop)await readLoop.catch(()=>{});reader=null;}
    if(writer){writer.releaseLock();writer=null;}
    if(port){await port.close().catch(()=>{});port=null;}
    attach.disabled=!('serial' in navigator);progress.hidden=true;
  }
  function waitFor(event,timeout=15000){
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{waiting=null;reject(Error('ESP did not respond. Check the firmware, press RESET, and reconnect.'));},timeout);
      waiting={event,resolve:value=>{clearTimeout(timer);waiting=null;resolve(value);},reject:error=>{clearTimeout(timer);waiting=null;reject(error);}};
    });
  }
  async function send(value){
    const bytes=new TextEncoder().encode(JSON.stringify(value)+'\n');
    for(let i=0;i<bytes.length;i+=32){await writer.write(bytes.slice(i,i+32));await new Promise(r=>setTimeout(r,50));}
  }
  async function command(value,event,timeout){const response=waitFor(event,timeout);try{await send(value);}catch(e){waiting?.reject(e);}return response;}
  function received(value){
    if(value.event==='printer'){
      knownPrinters.set(value.address,value);printers.replaceChildren(...[...knownPrinters.values()].map((p,i)=>{const option=element('option',`${p.name} · ${p.rssi>-65?'Nearby':'Weaker signal'} · ${i+1}`);option.value=p.address;return option;}));
    }
    if(value.event==='error'){waiting?.reject(Error(value.message));return;}
    if(waiting?.event===value.event)waiting.resolve(value);
  }
  async function readSerial(){
    const decoder=new TextDecoder();let buffer='';
    try{for(;;){const r=await reader.read();if(r.done)break;buffer+=decoder.decode(r.value,{stream:true});let end;
      while((end=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,end);buffer=buffer.slice(end+1);const at=line.indexOf('MCJSON:');if(at>=0){try{received(JSON.parse(line.slice(at+7)));}catch{}}}
      if(buffer.length>8192)buffer=buffer.slice(-4096);
    }}catch(e){waiting?.reject(e);}finally{reader.releaseLock();waiting?.reject(Error('ESP disconnected'));}
  }
  function busy(value){for(const b of [wifiScan,scan,test,save])b.disabled=value;networks.disabled=value;password.disabled=value;printers.disabled=value;if(!value){test.disabled=!printers.value;save.disabled=!tested;}}
  async function refreshWifi(){const result=await command({command:'scan_wifi'},'wifi',20000);const previous=networks.value;const unique=new Map(result.networks.map(n=>[n.ssid,n]));networks.replaceChildren(...[...unique.values()].map(n=>{const option=element('option',n.ssid);option.value=n.ssid;option.dataset.open=n.open?'yes':'no';return option;}));if(unique.has(previous))networks.value=previous;networks.onchange();}
  networks.onchange=()=>{const open=networks.selectedOptions[0]?.dataset.open==='yes';passwordLabel.hidden=open;if(open)password.value='';};
  attach.onclick=async()=>{
    attach.disabled=true;
    try{
      port=await navigator.serial.requestPort();await port.open({baudRate:115200});await port.setSignals({dataTerminalReady:false,requestToSend:false});
      reader=port.readable.getReader();writer=port.writable.getWriter();const ready=waitFor('ready',45000);readLoop=readSerial();
      message.textContent='Press RESET on the ESP. Waiting for guided setup…';await ready;
      const hello=await command({command:'hello'},'ready');if(hello.version<2)throw Error('Update the ESP firmware for guided setup.');
      serialReady=true;tested=false;knownPrinters.clear();printers.replaceChildren();progress.hidden=false;busy(true);
      await refreshWifi();message.textContent='Choose your Wi-Fi, then find your printer.';
    }catch(e){message.textContent=e.message;await release();}finally{busy(false);}
  };
  wifiScan.onclick=async()=>{busy(true);try{await refreshWifi();message.textContent='Wi-Fi list updated.';}catch(e){message.textContent=e.message;}finally{busy(false);}};
  scan.onclick=async()=>{busy(true);tested=false;knownPrinters.clear();printers.replaceChildren();message.textContent='Looking for nearby MXW01 printers…';try{await command({command:'scan_printers'},'printers_done',12000);message.textContent=printers.value?'Choose a printer and print a test to identify it.':'No compatible printer found. Turn it on, disconnect its phone app, and try again.';}catch(e){message.textContent=e.message;}finally{busy(false);}};
  printers.onchange=()=>{tested=false;save.disabled=true;};
  test.onclick=async()=>{busy(true);tested=false;message.textContent='Connecting and printing a small test…';try{await command({command:'test',address:printers.value},'test_done',65000);tested=true;message.textContent='Did the test print on your printer? If yes, save the connection. To choose another printer, disconnect USB, press RESET, and start again.';}catch(e){message.textContent=e.message;}finally{busy(false);}};
  save.onclick=async()=>{
    if(!serialReady||!tested||!networks.value){message.textContent='Choose Wi-Fi and confirm a test print first.';return;}
    busy(true);try{
      const r=await api('/api/printers/'+printer.id+'/connect',{address:printers.value,ssid:networks.value,password:password.value});
      await command((await r.json()).config,'saved',15000);password.value='';await release();message.textContent='Saved. The ESP is joining Wi-Fi. Its status will update when it reaches the app.';lastState='';await refresh();
    }catch(e){message.textContent=e.message;}finally{busy(false);}
  };
  close.onclick=async()=>{await release();message.textContent='USB disconnected. If setup was not saved, reset the ESP to resume its previous connection.';};
  box.addEventListener('toggle',()=>{if(!box.open&&port)release().catch(()=>{});});
  const remove=element('button','Delete printer','delete-printer');remove.type='button';
  remove.onclick=async()=>{
    if(!confirm(`Delete “${printer.name}”? This removes shared access and disconnects its ESP. Past prints are kept. You can add the printer again later.`))return;
    remove.disabled=true;
    try{await release();await api('/api/printers/'+printer.id,{},'DELETE');box.open=false;cancelSuggestion();$('printers').replaceChildren();lastState='';await refresh();notice('Printer deleted.');}
    catch(err){deleteMessage.textContent=err.message;}
    finally{remove.disabled=false;}
  };
  renameBox.append(rename,renameMessage);
  box.append(form,message);
  deleteBox.append(element('p','Remove this printer from your account and revoke shared access. Past prints are kept.','hint'),remove,deleteMessage);
  controls.append(box,renameBox,deleteBox);return controls;
}

// Keep the archive viewing preference on this browser, independent of album data.
function setPhotoSize(size){
  if(!['small','medium','large'].includes(size))size='medium';
  $('photoSize').value=size;$('gallery').dataset.size=size;
}
try{setPhotoSize(localStorage.getItem('memory-photo-size')||'medium');}catch{setPhotoSize('medium');}
$('photoSize').onchange=()=>{const size=$('photoSize').value;setPhotoSize(size);try{localStorage.setItem('memory-photo-size',size);}catch{}};

$('openArchiveView').onclick=()=>{
  const form=$('archiveViewForm');form.elements.density.value=$('photoSize').value;form.elements.sort.value=$('photoSort').value;
  const people=new Map(state.photos.map(p=>[p.contributor_id||'legacy',p.contributor||'Iris']));
  $('viewContributors').replaceChildren(...[...people].sort((a,b)=>a[1].localeCompare(b[1])).map(([id,name])=>{
    const label=element('label'),initials=element('span',name.split(/\s+/).map(word=>word[0]).slice(0,2).join('').toUpperCase(),'contributor-avatar');
    const check=element('input');check.type='checkbox';check.name='contributor';check.value=id;check.checked=contributorFilter.has(id);
    label.append(initials,element('span',name),check);return label;
  }));
  $('archiveView').showModal();
};
$('closeArchiveView').onclick=()=>$('archiveView').close();
$('resetArchiveView').onclick=()=>{const form=$('archiveViewForm');form.elements.density.value='medium';form.elements.sort.value='newest';for(const c of form.querySelectorAll('[name=contributor]'))c.checked=false;};
$('archiveViewForm').onsubmit=e=>{e.preventDefault();const form=e.currentTarget;setPhotoSize(form.elements.density.value);$('photoSort').value=form.elements.sort.value;contributorFilter=new Set([...form.querySelectorAll('[name=contributor]:checked')].map(c=>c.value));try{localStorage.setItem('memory-photo-size',$('photoSize').value);}catch{}draw();$('archiveView').close();};
$('archiveView').addEventListener('close',()=>$('openArchiveView').focus());

function isPhysicalJob(job){
  return job.physical || (job.state==='pending' && state.printers.some(p=>p.id===job.printer&&p.physical));
}
function updatePrinterInfo(info,p){
  info.replaceChildren();
  info.append(element('strong',p.name));
  if(p.physical){
    const recent=p.last_seen && Date.now()/1000-p.last_seen<30;
    info.append(element('small',`ESP: ${recent?'Online':'Offline'}`),element('small',`Printer: ${recent?(p.printer_connected===null?(p.online?'Connected':'Unknown'):(p.printer_connected?'Connected':'Disconnected')):'Unknown — ESP offline'}`),element('small',p.last_seen?`Last seen: ${new Date(p.last_seen*1000).toLocaleString()}`:'Last seen: not yet connected'));
  }else info.append(element('small','Setup needed · Connect an ESP'));
}
function drawPrinters(){
  const list=$('printers');
  // Preserve any setup/sharing form currently being edited during polling.
  if(!list.querySelector('details[open]')){
    const scroll=list.scrollLeft;
    list.replaceChildren(...state.printers.map(p=>{
      const card=element('div',undefined,'printer');card.dataset.printer=p.id;
      const info=element('div',undefined,'printer-heading');
      updatePrinterInfo(info,p);
      card.append(info);
      if(p.owner===account?.user.id)card.append(printerSetup(p),printerSharing(p));
      else card.append(element('p','Shared with you','hint'));
      return card;
    }));
    list.scrollLeft=scroll;
  }
  const query=$('printerSearch').value.trim().toLowerCase(), filter=$('printerFilter').value;
  let count=0;
  for(const card of list.children){
    const p=state.printers.find(p=>p.id===card.dataset.printer);
    if(p)updatePrinterInfo(card.querySelector('.printer-heading'),p);
    const match=p&&p.name.toLowerCase().includes(query)&&(filter==='all'||filter==='mine'&&p.owner===account?.user.id||filter==='shared'&&p.owner!==account?.user.id||filter==='online'&&p.physical&&p.online||filter==='setup'&&!p.physical);
    card.hidden=!match;if(match)count++;
  }
  $('printerEmpty').hidden=count>0;
  $('printerCount').textContent=`${count} ${count===1?'printer':'printers'}`;
}
$('printerSearch').oninput=drawPrinters;
$('printerFilter').onchange=drawPrinters;

$('caption').addEventListener('compositionstart',()=>{clearTimeout(timer);generation++;$('send').disabled=true;});
$('caption').addEventListener('compositionend',()=>$('caption').dispatchEvent(new Event('input',{bubbles:true})));
