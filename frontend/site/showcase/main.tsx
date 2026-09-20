import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {WikiWorkbench,type Bootstrap,type Run} from '../components/wiki-workbench';
import type {StudioStage} from '../lib/finals-stage';
import recording from './recording.json';
import '../app/globals.css';
import '../app/finals/wiki.css';
import '../app/finals/studio.css';
import './showcase.css';

function Showcase(){
 const [index,setIndex]=useState(-1);
 const snapshot=index<0?null:recording.snapshots[index];
 return <><header className="showcase-bar"><strong>演示回放</strong><nav aria-label="演示情节"><button aria-pressed={index===-1} onClick={()=>setIndex(-1)}>任务背景</button>{recording.snapshots.map((s,i)=><button key={s.label} aria-pressed={index===i} onClick={()=>setIndex(i)}>{s.label}</button>)}</nav></header>
 <WikiWorkbench key={index} preview={{boot:recording.boot as Bootstrap,run:(snapshot?.run ?? recording.snapshots[0].run) as Run,stage:snapshot?.stage as StudioStage ?? 'intake'}}/>
 </>;
}
window.parent.postMessage({isStreamlitMessage:true,type:'streamlit:componentReady',apiVersion:1},'*');
window.parent.postMessage({isStreamlitMessage:true,type:'streamlit:setFrameHeight',height:950},'*');
createRoot(document.getElementById('root')!).render(<Showcase/>);
