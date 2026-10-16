-- Bo database tables. Run this once in Neon's SQL Editor.
-- Safe to run again: it only creates what's missing.

-- People Bo talks to (you, playing the parent).
create table if not exists people (
  id            serial primary key,
  phone         text unique not null,          -- +1XXXXXXXXXX
  name          text,
  timezone      text not null default 'America/New_York',
  consented_at  timestamptz,                   -- null until they say YES
  created_at    timestamptz not null default now(),
  is_tester     boolean not null default false,  -- signed up on trustbo.ai
  portal_token  text unique                      -- secret part of their demo portal link
);

-- Every text and every spoken turn, so Bo remembers across channels.
create table if not exists messages (
  id          bigserial primary key,
  person_id   int not null references people(id) on delete cascade,
  role        text not null check (role in ('user', 'assistant')),
  content     text not null,
  channel     text not null default 'sms',      -- 'sms', 'whatsapp' or 'voice'
  created_at  timestamptz not null default now()
);
create index if not exists messages_person_idx on messages (person_id, id);

-- Links an ElevenLabs call to a person, so the transcript lands in the right place.
create table if not exists calls (
  conversation_id  text primary key,
  person_id        int not null references people(id) on delete cascade,
  started_at       timestamptz not null default now()
);

-- ── Stand-in for the clinic's portal ──────────────────────────────────────
-- In the real product this data lives in the clinic's system (MyChart etc.).
-- For the prototype it's these two tables, filled with made-up data.
create table if not exists appointments (
  id          serial primary key,
  person_id   int not null references people(id) on delete cascade,
  title       text not null,
  provider    text,
  location    text,
  starts_at   timestamptz not null,
  status      text not null default 'scheduled'
);

-- Each person gets their own open slots, so testers never compete for the same time.
create table if not exists open_slots (
  id          serial primary key,
  person_id   int references people(id) on delete cascade,
  provider    text not null,
  starts_at   timestamptz not null,
  taken       boolean not null default false
);

-- Upgrades for databases created before tester sign-up existed (safe to re-run).
alter table people     add column if not exists is_tester    boolean not null default false;
alter table people     add column if not exists portal_token text unique;
alter table open_slots add column if not exists person_id    int references people(id) on delete cascade;
