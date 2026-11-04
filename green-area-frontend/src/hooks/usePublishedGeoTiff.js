import {useCallback,useEffect,useRef,useState} from 'react';
import {gisRequest} from '../utils/gisClient';
import {CURRENT_YEAR} from '../constants';
import {publishedSnapshotMatches} from '../utils/publishedAnalysis';

export function usePublishedGeoTiff(){
  const [source,setSourceRaw]=useState('legacy');
  const [scope,setScopeRaw]=useState({province:'',data_year:CURRENT_YEAR,month:0,product:'ndvi'});
  const [record,setRecord]=useState(null),[error,setError]=useState(''),[loading,setLoading]=useState(false);
  const abort=useRef(null),last=useRef(null);const scopeKey=JSON.stringify(scope);
  const clear=useCallback(()=>{abort.current?.abort();abort.current=null;setRecord(null);setError('');setLoading(false);last.current=null;},[]);
  const setSource=useCallback(v=>{clear();setSourceRaw(v==='published'?'published':'legacy');},[clear]);
  const setScope=useCallback(v=>{clear();setScopeRaw(s=>({...s,...v}));},[clear]);
  const fetchScope=useCallback(async target=>{
    abort.current?.abort();const c=new AbortController();abort.current=c;last.current=target;
    setRecord(null);setError('');setLoading(true);
    try{
      if(!target.province)throw Error('กรุณาเลือกจังหวัด');
      const bundle=await gisRequest('/published-geotiff',{query:{...target,coverage_mode:'source_footprint_intersection'},signal:c.signal});
      if(!publishedSnapshotMatches(bundle,target))throw Error('Snapshot หรือขอบเขตข้อมูลไม่ตรงกัน');
      if(!c.signal.aborted)setRecord({key:JSON.stringify(target),bundle});
    }catch(e){if(!c.signal.aborted)setError(e.message||'Published GeoTIFF ไม่พร้อมใช้งาน ไม่มีการใช้ Legacy แทน');}
    finally{if(abort.current===c){abort.current=null;setLoading(false);}}
  },[]);
  const load=useCallback(()=>fetchScope(scope),[fetchScope,scope]);
  useEffect(()=>{
    if(source!=='published')return;
    const recheck=()=>{if(last.current&&document.visibilityState!=='hidden')fetchScope(last.current);};
    const tick=()=>{if(!abort.current)recheck();};
    const visible=()=>{if(document.visibilityState==='hidden'){abort.current?.abort();setRecord(null);}else recheck();};
    const timer=setInterval(tick,10000);window.addEventListener('focus',recheck);window.addEventListener('gis-geotiff-publication-change',recheck);document.addEventListener('visibilitychange',visible);
    const channel=typeof BroadcastChannel==='function'?new BroadcastChannel('gis-geotiff-publication'):null;if(channel)channel.onmessage=recheck;
    return()=>{clearInterval(timer);abort.current?.abort();channel?.close();window.removeEventListener('focus',recheck);window.removeEventListener('gis-geotiff-publication-change',recheck);document.removeEventListener('visibilitychange',visible);};
  },[source,fetchScope]);
  useEffect(()=>()=>abort.current?.abort(),[]);
  return {source,setSource,scope,setScope,load,error,loading,bundle:source==='published'&&record?.key===scopeKey?record.bundle:null};
}
