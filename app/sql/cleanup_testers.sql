-- Deletes testers who signed up more than 24 hours ago, with their appointments,
-- open slots, messages and calls. Bo also does this by itself (on every sign-up and once a day),
-- so you only need this to clean up by hand.

delete from people
where is_tester
  and created_at < now() - interval '24 hours';

-- To see who has signed up:
-- select name, phone, created_at from people where is_tester order by created_at desc;
