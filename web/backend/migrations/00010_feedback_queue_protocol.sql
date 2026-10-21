-- +goose Up
-- 隔离不识别审核状态的旧 worker；回滚程序时数据库不会自动降级。
-- 旧 API 回滚后仍可能写旧键，必须在数据库边界移除所有旧 worker 可读的编号。
-- +goose StatementBegin
CREATE FUNCTION normalize_reviewed_feedback_job() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
 feedback_id text;
BEGIN
 IF NEW.kind='FEEDBACK_GITHUB' THEN
  feedback_id := coalesce(NEW.payload->>'reviewedFeedbackId',NEW.payload->>'feedbackId');
  IF feedback_id IS NULL OR feedback_id='' THEN
   RAISE EXCEPTION 'feedback job identifier required';
  END IF;
  NEW.payload := jsonb_build_object('reviewedFeedbackId',feedback_id);
 END IF;
 RETURN NEW;
END;
$$;
-- +goose StatementEnd
CREATE TRIGGER reviewed_feedback_job_payload
 BEFORE INSERT OR UPDATE OF payload,kind ON jobs
 FOR EACH ROW EXECUTE FUNCTION normalize_reviewed_feedback_job();

-- 先建立触发器取得写互斥表锁，再重写历史任务，封住仍在线旧 API 的并发写入窗口。
UPDATE jobs SET payload=jsonb_build_object('reviewedFeedbackId',coalesce(payload->>'reviewedFeedbackId',payload->>'feedbackId'))
 WHERE kind='FEEDBACK_GITHUB';

-- +goose Down
DROP TRIGGER reviewed_feedback_job_payload ON jobs;
DROP FUNCTION normalize_reviewed_feedback_job();
UPDATE jobs SET payload=jsonb_build_object('feedbackId',payload->>'reviewedFeedbackId')
 WHERE kind='FEEDBACK_GITHUB';
