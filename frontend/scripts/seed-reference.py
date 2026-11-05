"""Explicit local demo fixtures. Run with the reference backend's environment and PYTHONPATH.
Never runs at application startup; never contacts a real email address.
"""
import asyncio
import os
from datetime import date
from decimal import Decimal
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.auth.security import hash_password
from app.users.models import User
from app.companies.models import Company
from app.jobs.models import Job
from app.friends.models import Friendship
from app.conversations.models import Conversation, ConversationParticipant, Message

PASSWORD = 'WozuDemo!2026'
COMPANIES = [('Orbit Studio','Senior Product Designer','Design thoughtful digital experiences with a small, ambitious team. You will shape our design system, talk to customers, and take ideas from a sketch to something people love.\n\nWhat you bring\n• Strong visual craft and product thinking\n• Figma, prototyping, and clear communication\n• Curiosity about the people using your work\n\nWhat we offer\n• Time to do meaningful work\n• A collaborative team and room to grow\n• A flexible, supportive environment',22000,'Abu Dhabi, UAE',24.4539,54.3773),('Palm Labs','Frontend Engineer','Build beautifully useful interfaces for a new generation of digital products. Work closely with design and backend teams on accessible, responsive React experiences.\n\nYou care about TypeScript, thoughtful interactions, readable code, and making the web work for everyone.',26000,'Dubai, UAE',25.2048,55.2708),('Bloom Collective','Brand & Visual Designer','Help ambitious brands find their voice. Bring expressive typography, thoughtful art direction, and a love for the small details to a close-knit creative team.\n\nYour portfolio tells a story. We would love to meet the person behind it.',16000,'Abu Dhabi, UAE',24.49,54.37),('Forma','UX Researcher','Make sure the right questions get asked. Plan research, listen deeply, and turn observations into clear product direction.\n\nYou will work with people across design, engineering, and strategy to build experiences grounded in real needs.',18500,'Baku, Azerbaijan',40.4093,49.8671),('Gather & Co.','Community Manager','Bring people together around work that matters. Create thoughtful events, support our growing community, and help every new member feel at home.\n\nYou are a generous communicator with a natural eye for connection.',12000,'Dubai, UAE',25.17,55.25),('Morrow','Creative Developer','Where craft meets code. Turn ambitious ideas into fast, expressive, accessible websites and interactive experiences.\n\nBring your eye for motion, your curiosity, and your confidence with modern web technologies.',24000,'Abu Dhabi, UAE',24.43,54.45)]

async def main():
    if os.getenv('ENV') == 'prod' or 'wozu_frontend_dev' not in os.environ.get('DATABASE_URL',''):
        raise SystemExit('Seed is restricted to the isolated wozu_frontend_dev database.')
    async with AsyncSessionLocal() as db:
        async def user(email,first,last,position):
            existing=await db.scalar(select(User).where(User.email==email))
            if existing:return existing
            u=User(email=email,password_hash=hash_password(PASSWORD),is_email_verified=True,first_name=first,last_name=last,position=position,birth_date=date(1998,4,12),bio='Demo account for exploring the WOZU development workspace.',status='active')
            db.add(u);await db.flush();return u
        candidate=await user('candidate@example.com','Alex','Morgan','Product Designer')
        friend=await user('friend@example.com','Sam','Rivera','Frontend Engineer')
        for index,(name,title,description,salary,location,lat,lng) in enumerate(COMPANIES):
            owner=await user('employer@example.com' if index==0 else f'employer{index+1}@example.com',name.split()[0],'Team','Talent Partner')
            company=await db.scalar(select(Company).where(Company.owner_user_id==owner.id))
            if not company:
                company=Company(owner_user_id=owner.id,name=name,description='Fictional company for local demonstration.',country='United Arab Emirates' if 'UAE' in location else 'Azerbaijan',city=location.split(',')[0],status='active',created_by_id=owner.id,updated_by_id=owner.id)
                db.add(company);await db.flush()
            job=await db.scalar(select(Job).where(Job.owner_id==company.id,Job.title==title))
            if not job:
                db.add(Job(owner_id=company.id,title=title,description=description,status='open',latitude=lat,longitude=lng,location=location,salary_amount=Decimal(salary),salary_currency='AED' if 'UAE' in location else 'AZN',salary_type='monthly',schedule='full_time' if index!=4 else 'part_time',urgency='urgent' if index in [0,2] else 'normal',created_by_id=owner.id,updated_by_id=owner.id))
        friendship=await db.scalar(select(Friendship).where(Friendship.requester_id==candidate.id,Friendship.addressee_id==friend.id))
        if not friendship: db.add(Friendship(requester_id=candidate.id,addressee_id=friend.id,status='accepted'))
        conversation=await db.scalar(select(Conversation).where(Conversation.title=='Sam Rivera · Demo conversation'))
        if not conversation:
            conversation=Conversation(type='direct',title='Sam Rivera · Demo conversation');db.add(conversation);await db.flush()
            db.add_all([ConversationParticipant(conversation_id=conversation.id,user_id=u.id,role='member') for u in [candidate,friend]])
            message=Message(conversation_id=conversation.id,author_id=friend.id,content='Hey Alex! Welcome to the demo workspace. This is a seeded conversation — send a message to try the real chat API.',status='sent',message_type='text');db.add(message);await db.flush();conversation.last_message_id=message.id
        await db.commit()
    print('Demo accounts, six opportunities, one friendship, and one conversation are ready.')
    print('Accounts: candidate@example.com / employer@example.com / friend@example.com')
    print('Password: WozuDemo!2026 (local demo only)')

asyncio.run(main())
