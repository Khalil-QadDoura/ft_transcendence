"""Integration smoke test against the isolated demo database. No external accounts.
Runs real HTTP + WebSocket flows, including a complete server-timed game (~3 min).
"""
import asyncio
import json
import os
import pathlib
import uuid
import httpx
import websockets

BASE = 'http://127.0.0.1:8000'
PASSWORD = 'WozuDemo!2026'

async def main():
    assert 'wozu_frontend_dev' in os.environ.get('DATABASE_URL', ''), 'Only the isolated demo database is allowed'
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as http:
        async def request(method, path, token=None, body=None, expected=200):
            response = await http.request(method, path, headers={'Authorization': f'Bearer {token}'} if token else {}, json=body)
            assert response.status_code == expected, f'{method} {path}: expected {expected}, got {response.status_code}: {response.text[:300]}'
            return response.json() if response.content else None
        candidate = await request('POST', '/auth/login', body={'email':'candidate@example.com','password':PASSWORD})
        employer = await request('POST', '/auth/login', body={'email':'employer@example.com','password':PASSWORD})
        c, e = candidate['access_token'], employer['access_token']
        rotated = await request('POST', '/auth/refresh', body={'refresh_token':candidate['refresh_token']})
        await request('POST', '/auth/refresh', body={'refresh_token':candidate['refresh_token']}, expected=401)
        c = rotated['access_token']
        me = await request('GET', '/users/me', c)
        await request('GET', '/users/me', expected=401)
        print('PASS authentication, refresh rotation, unauthorized guard', flush=True)
        jobs = await request('GET', '/jobs/open?limit=20')
        assert len(jobs['items']) >= 6
        mine = await request('GET', '/jobs/mine', e)
        job = next(j for j in mine if j['title'] == 'Senior Product Designer')
        await request('PATCH', '/users/me', c, {k:me[k] for k in ['first_name','last_name','position','birth_date','bio']})
        applications = await request('GET', '/applications/mine?limit=20', c)
        application = next((a for a in applications['items'] if a['job_id']==job['id']), None)
        if application is None:
            application = await request('POST', f"/jobs/{job['id']}/apply", c, {'cover_note':'Explicit local integration test application.'}, 201)
        await request('POST', f"/jobs/{job['id']}/apply", c, {}, 409)
        await request('GET', f"/jobs/{job['id']}/applications", c, expected=403)
        for status in ['shortlisted','contacted']:
            if application['status'] in ('submitted','viewed') or (application['status']=='shortlisted' and status=='contacted'):
                application = await request('PATCH', f"/applications/{application['id']}/status", e, {'status':status})
        assert application['conversation_id']
        intro = await request('GET', f"/applications/{application['id']}/video", e)
        assert (await http.get(intro['signed_url'])).status_code == 200
        friend = await request('POST', '/auth/login', body={'email':'friend@example.com','password':PASSWORD})
        await request('GET', f"/applications/{application['id']}/video", friend['access_token'], expected=403)
        await request('POST','/auth/logout',body={'refresh_token':friend['refresh_token']},expected=204)
        draft = {'title':'Local integration test opportunity','description':'An explicitly disposable job created by the local integration check.','location':'Baku, Azerbaijan','latitude':40.4093,'longitude':49.8671,'salary_amount':1000,'salary_currency':'AZN','salary_type':'monthly','schedule':'full_time','urgency':'normal','status':'active'}
        created = await request('POST', '/jobs', e, draft, 201)
        changed = await request('PATCH', f"/jobs/{created['id']}", e, {'title':'Updated local integration opportunity'})
        assert changed['title']=='Updated local integration opportunity'
        await request('DELETE', f"/jobs/{created['id']}", e, expected=204)
        print('PASS discovery, profile, application duplicate/ownership guards, employer transitions', flush=True)
        conversation = await request('POST', '/conversations', c, {'type':'direct','peer_user_id':2}, 201)
        cid = conversation['id']
        key = str(uuid.uuid4())
        message = (await request('POST', f'/conversations/{cid}/messages', c, {'content':'Local integration test message','idempotency_key':key}))['items'][0]
        retry = (await request('POST', f'/conversations/{cid}/messages', c, {'content':'Local integration test message','idempotency_key':key}))['items'][0]
        assert message['id'] == retry['id']
        await request('PATCH', f"/conversations/{cid}/messages/{message['id']}", c, {'content':'Local integration test message edited'})
        await request('DELETE', f"/conversations/{cid}/messages/{message['id']}", c, expected=204)
        print('PASS chat persistence, idempotency, edit and delete', flush=True)
        videos = await request('GET', '/media/intro-video/mine', c)
        fixture = next(v for v in videos['items'] if v['moderation_status']=='approved')
        media = await http.get(fixture['signed_url'])
        assert media.status_code == 200 and len(media.content)>1000
        upload = await request('POST', '/media/intro-video/upload-url', c, {'content_type':'video/mp4','ext':'mp4','expires_sec':900})
        put = await http.put(upload['put_url'], content=media.content, headers={'Content-Type':'video/mp4','Origin':'http://127.0.0.1:5173'})
        assert put.status_code == 200
        assert put.headers.get('access-control-allow-origin') in ('*','http://127.0.0.1:5173')
        confirmed = await request('POST', '/media/intro-video/confirm', c, {'object_key':upload['object_key'],'duration_sec':6,'size_bytes':len(media.content),'content_type':'video/mp4'}, 201)
        assert confirmed['moderation_status']=='pending'
        await request('POST', f"/media/intro-video/{confirmed['id']}/post", c, expected=409)
        await request('POST', f"/media/intro-video/{confirmed['id']}/delete", c)
        await request('POST', '/media/avatar/confirm', c, {'object_key':'avatars/999/00000000-0000-0000-0000-000000000000.png'}, 400)
        print('PASS signed media playback/upload, CORS, confirmation, unapproved-publication guard, avatar ownership', flush=True)
        if os.environ.get('WOZU_CHECK_GAME') == '0':
            await request('POST','/auth/logout',body={'refresh_token':rotated['refresh_token']},expected=204)
            await request('POST','/auth/logout',body={'refresh_token':employer['refresh_token']},expected=204)
            print('ALL HTTP INTEGRATION CHECKS PASSED (game explicitly skipped)', flush=True)
            return
        async with websockets.connect(f'ws://127.0.0.1:8000/ws?token={c}') as global_ws:
            await request('POST', '/game/queue/join', c, expected=202)
            while True:
                event = json.loads(await asyncio.wait_for(global_ws.recv(), 45))
                if event.get('type') == 'game_room_formed':
                    room_id = event['payload']['room_id']; break
        path = f'/game/rooms/{room_id}'
        room = await request('GET', path, c)
        assert room['self_participant_id'] and room['phase_ends_at']
        await request('GET', path, e, expected=403)
        await request('POST', path+'/votes', c, {'target_participant_id':999999,'guess':'bot'}, 409)
        async with websockets.connect(f'ws://127.0.0.1:8000/game/ws?token={c}&room_id={room_id}') as ws:
            await ws.send(json.dumps({'type':'chat_message','text':'Local integration test: what makes a good day?'}))
            while True:
                event = json.loads(await asyncio.wait_for(ws.recv(), 15))
                if event.get('type')=='game_message' and event['payload']['participant_id']==room['self_participant_id']: break
        restored = await request('GET', path, c)
        assert any(m['text'].startswith('Local integration test:') for m in restored['messages'])
        print('PASS matchmaking, game WebSocket delivery, membership guard, persisted reconnect history; waiting for voting', flush=True)
        for _ in range(70):
            room = await request('GET', path, c)
            if room['state']=='voting': break
            await asyncio.sleep(2)
        assert room['state']=='voting'
        await request('POST', path+'/votes', c, {'target_participant_id':999999,'guess':'bot'}, 400)
        await request('POST', path+'/votes', c, {'target_participant_id':room['self_participant_id'],'guess':'human'}, 400)
        for player in room['participants']:
            if player['id'] != room['self_participant_id']:
                await request('POST', path+'/votes', c, {'target_participant_id':player['id'],'guess':'bot'}, 201)
        restored = await request('GET', path, c)
        assert len(restored['my_votes']) == len(room['participants']) - 1
        for _ in range(30):
            room = await request('GET', path, c)
            if room['state']=='finished': break
            await asyncio.sleep(2)
        results = await request('GET', path+'/results', c)
        assert results['state']=='finished'
        print('PASS voting, self/cross-room vote guards, persisted votes, server-timed results', flush=True)
        await request('POST','/auth/logout',body={'refresh_token':rotated['refresh_token']},expected=204)
        await request('POST','/auth/logout',body={'refresh_token':employer['refresh_token']},expected=204)
        print('ALL REFERENCE INTEGRATION CHECKS PASSED', flush=True)

asyncio.run(main())
