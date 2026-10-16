-- One-time upgrade for tester sign-up. Run this once in Neon's SQL Editor.
-- Safe to run again.

alter table people     add column if not exists is_tester    boolean not null default false;
alter table people     add column if not exists portal_token text unique;
alter table open_slots add column if not exists person_id    int references people(id) on delete cascade;

-- Open slots now belong to one person. Give the existing ones to you.
update open_slots
set person_id = (select id from people where phone = '+14129968951')   -- <- your mobile, with +1
where person_id is null;
