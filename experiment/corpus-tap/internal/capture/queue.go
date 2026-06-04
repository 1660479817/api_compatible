package capture

// Queue submits records to a Recorder with bounded backpressure.
type Queue struct {
	rec *Recorder
	ch  chan Record
}

func NewQueue(rec *Recorder, workers, bufsize int) *Queue {
	if workers < 1 {
		workers = 1
	}
	if bufsize < 1 {
		bufsize = 64
	}
	q := &Queue{rec: rec, ch: make(chan Record, bufsize)}
	for i := 0; i < workers; i++ {
		go func() {
			for rec := range q.ch {
				q.rec.Persist(rec.Ctx, rec)
			}
		}()
	}
	return q
}

// Submit enqueues a record. Returns false if queue is full (caller sets store_error=queue_full).
func (q *Queue) Submit(rec Record) bool {
	select {
	case q.ch <- rec:
		return true
	default:
		return false
	}
}
