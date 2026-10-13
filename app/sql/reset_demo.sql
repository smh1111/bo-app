-- Fills Bo with made-up appointments for you, and wipes earlier test chats.
-- Run it after schema.sql, and again before every demo to start fresh.
--
-- EDIT THE THREE LINES MARKED "<-" FIRST.

do $$
declare
  my_phone  text := '+15555550123';       -- <- your mobile, with +1
  my_name   text := 'Shama';              -- <- what Bo should call you
  my_tz     text := 'America/New_York';   -- <- your time zone
  pid       int;
  day0      timestamp;
begin
  day0 := date_trunc('day', now() at time zone my_tz);

  insert into people (phone, name, timezone, consented_at)
  values (my_phone, my_name, my_tz, null)
  on conflict (phone) do update
    set name = excluded.name, timezone = excluded.timezone, consented_at = null
  returning id into pid;

  delete from messages     where person_id = pid;
  delete from calls        where person_id = pid;
  delete from appointments where person_id = pid;
  delete from open_slots;

  insert into appointments (person_id, title, provider, location, starts_at) values
    (pid, 'Dental cleaning',      'Dr. Priya Shah', 'Bright Smile Dental',     (day0 + interval '3 days 14 hours')            at time zone my_tz),
    (pid, 'Cardiology follow-up', 'Dr. Lin',        'Heart & Vascular Clinic', (day0 + interval '8 days 10 hours 30 minutes') at time zone my_tz),
    (pid, 'Annual physical',      'Dr. Okafor',     'Maple Family Medicine',   (day0 + interval '15 days 9 hours')            at time zone my_tz);

  insert into open_slots (provider, starts_at) values
    ('Dr. Priya Shah', (day0 + interval '2 days 10 hours')             at time zone my_tz),
    ('Dr. Priya Shah', (day0 + interval '4 days 11 hours 30 minutes')  at time zone my_tz),
    ('Dr. Priya Shah', (day0 + interval '5 days 15 hours')             at time zone my_tz),
    ('Dr. Priya Shah', (day0 + interval '7 days 9 hours')              at time zone my_tz),
    ('Dr. Lin',        (day0 + interval '9 days 13 hours')             at time zone my_tz),
    ('Dr. Lin',        (day0 + interval '10 days 9 hours 30 minutes')  at time zone my_tz),
    ('Dr. Lin',        (day0 + interval '12 days 15 hours 15 minutes') at time zone my_tz),
    ('Dr. Okafor',     (day0 + interval '14 days 11 hours')            at time zone my_tz),
    ('Dr. Okafor',     (day0 + interval '16 days 14 hours')            at time zone my_tz);
end $$;

-- Optional: skip the "Reply YES" step during a demo by uncommenting this line.
-- update people set consented_at = now() where phone = '+15555550123';
