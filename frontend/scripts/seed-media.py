"""Explicit approved local media fixture, not an AI moderation result."""
import asyncio
import os
import pathlib
import subprocess
import tempfile
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.users.models import User
from app.media.models import IntroVideo
from app.media.minio_client import MinioClient

async def main():
    assert 'wozu_frontend_dev' in os.environ.get('DATABASE_URL',''), 'Only the isolated demo database is allowed'
    storage = MinioClient.instance(); storage.ensure_bucket()
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / 'introduction.mp4'
        subprocess.run(['ffmpeg','-y','-f','lavfi','-i','color=c=0x153c30:s=720x960:r=24','-vf',"drawtext=text='WOZU / LOCAL DEMO':fontcolor=0xd6ec9d:fontsize=38:x=(w-tw)/2:y=h/2-55,drawtext=text='Alex Morgan - Product Designer':fontcolor=white:fontsize=24:x=(w-tw)/2:y=h/2+20",'-t','6','-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(path)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        async with AsyncSessionLocal() as db:
            user = await db.scalar(select(User).where(User.email=='candidate@example.com'))
            if not user: raise SystemExit('Run seed first.')
            key = f'users/{user.id}/intro/local-demo-fixture.mp4'
            storage.client.fput_object(storage.cfg.bucket,key,str(path),content_type='video/mp4')
            existing = await db.scalar(select(IntroVideo).where(IntroVideo.object_key==key))
            if not existing:
                db.add(IntroVideo(user_id=user.id,object_key=key,duration_sec=6,size_bytes=path.stat().st_size,content_type='video/mp4',moderation_status='approved',lifecycle_status='posted',video_rating='B',created_by_id=user.id,updated_by_id=user.id))
            await db.commit()
    print('Approved local fixture prepared. No AI moderation was run.')
asyncio.run(main())
