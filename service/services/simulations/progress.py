"""Validate bounded progress received from the isolated simulator."""


def valid_progress(progress):
    if not isinstance(progress, dict):
        return False
    phase, done, total = progress.get('phase'), progress.get('done'), progress.get('total')
    if type(done) is not int or type(total) is not int:
        return False
    if phase in ('feedback_network', 'feedback_cells'):
        if (set(progress) != {'phase', 'iteration', 'done', 'total'}
                or type(progress['iteration']) is not int or not 1 <= progress['iteration'] <= 100):
            return False
        return (done == total == 0 if phase == 'feedback_network'
                else 0 < done <= total <= 256)
    if set(progress) != {'phase', 'done', 'total'}:
        return False
    if phase == 'field':
        return 0 <= done <= total <= 166700 and total > 0
    if phase == 'field_verification':
        return done == total == 0
    return ((done == total == 0 or 0 <= done <= total <= 1000 and total > 0) if phase == 'network'
            else phase in ('geometry', 'cells') and 0 < done <= total <= 256)
