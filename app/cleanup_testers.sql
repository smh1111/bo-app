-- Deletes testers who signed up more than 14 days ago, with their appointments,
-- open slots, messages and calls. Run it in Neon's SQL Editor whenever you like.

delete from people
where is_tester
  and created_at < now() - interval '14 days';

-- To see who has signed up:
-- select name, phone, created_at from people where is_tester order by created_at desc;
