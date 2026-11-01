"""Normalize local playback metadata without guessing undocumented event types."""
from datetime import datetime, timedelta


def recording_rows(raw):
    found={}
    def walk(node):
        if isinstance(node,dict):
            if 'startTime' in node and 'endTime' in node:
                start,end=int(node['startTime']),int(node['endTime'])
                if end<=start:raise ValueError('Invalid recording interval')
                row=found.setdefault((start,end),{'start':start,'end':end,'events':[],'recording_type':None})
                value=node.get('video_type',node.get('vedio_type'))
                if value is not None:row['recording_type']=str(value)
            else:
                for value in node.values():walk(value)
        elif isinstance(node,list):
            for value in node:walk(value)
    walk(raw)
    if raw and not found:raise ValueError('Unrecognized recording response')
    return [found[key] for key in sorted(found)]


def normalize_events(raw):
    result={}
    if not isinstance(raw,list):raise ValueError('Unrecognized detection response')
    for event in raw:
        if not isinstance(event,dict):continue
        try:
            start,end=int(event['start_time']),int(event['end_time'])
            if end<start:continue
            kind=int(event['alarm_type']) if 'alarm_type' in event else None
            flags=int(event['events_1']) if 'events_1' in event else None
        except (KeyError,TypeError,ValueError):continue
        # Only numeric playback fields cross the worker boundary, never raw protocol data.
        row={'start':start,'end':end,'type':kind,'flags':flags}
        result[(start,end,kind,flags)]=row
    return sorted(result.values(),key=lambda row:(row['start'],row['end'],str(row['type']),str(row['flags'])))


def detection_metadata(cam,date,rows,cancelled):
    day=datetime.strptime(date,'%Y%m%d')
    correction=cam.getTimeCorrection()
    lower=int(day.timestamp());upper=int((day+timedelta(days=1)).timestamp())
    complete=True
    def fetch(start,end):
        nonlocal complete
        if cancelled():
            import asyncio
            raise asyncio.CancelledError()
        data=cam.getEvents(start-correction,end-1-correction)
        if len(data)>=1000:
            if end-start>1:
                middle=(start+end)//2
                return fetch(start,middle)+fetch(middle,end)
            complete=False
        return data
    events=normalize_events(fetch(lower,upper))
    events=[e for e in events if e['start']<upper and e['end']>=lower]
    for row in rows:
        row['events']=[e for e in events if e['start']<row['end'] and e['end']>=row['start']]
    return {'event_count':len(events),'events_complete':complete,'events_available':True}


def has_detection(row):
    return bool(row.get('events')) or row.get('recording_type') not in (None,'1','0')


def detection_label(row):
    count=len(row.get('events',[]))
    if count:return f'{count} event'+('s' if count!=1 else '')
    if has_detection(row):return 'Detection'
    if row.get('recording_type')=='1':return 'Continuous'
    return 'Not reported'
