"""Preview video suggestions (onco-video-links/v1 map) — synthetic HTTP checks.

Suggestions are additive candidates: they must be listed for the mapped
modules, stay provisional, never auto-satisfy the lecture requirement and
never change the materials version (existing teacher bindings survive).
All requests stay on the loopback test server with an isolated DB.
"""
import copy
import json
import urllib.request

from pilot.completion_fixture import CompletionFixture, DATA
from pilot.materials import Materials

SUGGESTIONS = {
    'schema': 'onco-video-links/v1',
    'videos': [{'video_id': 'V1',
                'mp4_url': 'https://video.test/v1.mp4',
                'youtube_url': 'https://youtube.test/v1',
                'duration_seconds_floor_or_ui': 100,
                'lecture_ids': ['L1', 'L2']}],
    'lectures': [
        {'lecture_id': 'L1', 'video_id': 'V1', 'modules': ['M01'],
         'title': 'Synthetic lecture one', 'speaker': 'Speaker One',
         'estimated_start': {'lower': 10, 'upper': 20},
         'estimated_end': {'lower': 80, 'upper': 90},
         'launch_offset_seconds': 10, 'boundary_status': 'provisional',
         'truncation_risk': False, 'truncation_warning': None,
         'youtube_start_url': 'https://youtube.test/v1?t=10s'},
        {'lecture_id': 'L2', 'video_id': 'V1', 'modules': ['M01'],
         'title': 'Synthetic truncated lecture', 'speaker': 'Speaker Two',
         'estimated_start': {'lower': 30, 'upper': 40},
         'estimated_end': None,
         'launch_offset_seconds': 30, 'boundary_status': 'provisional',
         'truncation_risk': True, 'truncation_warning': 'Possible cut',
         'youtube_start_url': 'https://youtube.test/v1?t=30s'},
        {'lecture_id': 'L3', 'video_id': 'V1', 'modules': ['M49'],
         'title': 'M49-only lecture', 'speaker': 'Speaker Three',
         'estimated_start': {'lower': 0, 'upper': 5},
         'estimated_end': {'lower': 90, 'upper': 95},
         'launch_offset_seconds': 0, 'boundary_status': 'provisional',
         'truncation_risk': False, 'truncation_warning': None,
         'youtube_start_url': 'https://youtube.test/v1?t=0s'}],
    'module_index': {'M01': ['L1', 'L2'], 'M49': ['L3']},
}


class VideoSuggestionTests(CompletionFixture):
    def inject(self):
        self.server.pilot.materials.set_suggestions(copy.deepcopy(SUGGESTIONS))

    def faculty(self, module='M01'):
        return self.get(self.a, '/api/modules/' + module)[1]['materials']['faculty_videos']

    def lecture_check(self):
        return next(c for c in self.state()['checks'] if c['id'] == 'lecture')

    def test_suggestions_listed_but_do_not_satisfy_requirement(self):
        self.inject()
        ids = [v['id'] for v in self.faculty()]
        self.assertIn('suggested-L1', ids)
        self.assertIn('suggested-L2', ids)
        self.assertNotIn('suggested-L3', ids)  # L3 is mapped to M49 only
        check = self.lecture_check()
        self.assertFalse(check['ok'])
        self.assertFalse(self.state()['student_ready'])

    def test_suggestions_do_not_change_materials_version(self):
        before = self.get(self.a, '/api/modules/M01')[1]['materials']['version']
        self.inject()
        after = self.get(self.a, '/api/modules/M01')[1]['materials']['version']
        self.assertEqual(before, after)

    def test_existing_binding_survives_suggestions(self):
        self.bind_lecture()
        self.inject()
        cat = self.get(self.t, '/api/completion/lecture/M01')[1]
        self.assertIsNotNone(cat['current'])
        self.assertEqual(cat['current']['resource'], self.lecture_id)

    def test_teacher_sees_and_can_bind_suggestion(self):
        self.inject()
        cat = self.get(self.t, '/api/completion/lecture/M01')[1]
        cand = {c['id']: c for c in cat['candidates']}
        self.assertIn('suggested-L1', cand)
        self.assertTrue(cand['suggested-L1']['suggested'])
        self.assertTrue(cand['suggested-L2']['truncation_risk'])
        code, body = self.get(self.t, '/api/completion/lecture', {
            'module': 'M01', 'materials_version': cat['materials_version'],
            'resource': 'suggested-L1', 'key': 'bind-s1'})
        self.assertEqual(code, 200, body)
        self.assertEqual(body['resource'], 'suggested-L1')
        # Only after binding + student opening does the lecture check pass.
        self.assertFalse(self.lecture_check()['ok'])
        self.assertEqual(self.open_resource('suggested-L1')[0], 200)
        self.assertTrue(self.lecture_check()['ok'])

    def test_provisional_and_truncation_fields_exposed(self):
        self.inject()
        videos = {v['id']: v for v in self.faculty()}
        l2 = videos['suggested-L2']
        self.assertEqual(l2['boundary_status'], 'provisional')
        self.assertTrue(l2['truncation_risk'])
        self.assertTrue(l2['truncation_warning'])
        self.assertIsNone(l2['estimated_end'])
        self.assertEqual(l2['url'], 'https://youtube.test/v1?t=30s')
        self.assertEqual(videos['suggested-L1']['launch_offset_seconds'], 10)

    def test_unmapped_module_has_no_suggestions(self):
        data = json.loads(self.data.read_text())
        mat = Materials(data)
        mat.set_suggestions(copy.deepcopy(SUGGESTIONS))
        other = copy.deepcopy(DATA['modules'][0])
        other['module_id'] = 'M02'
        kinds = [v['kind'] for v in mat.view(other)['faculty_videos']]
        self.assertNotIn('suggested_video', kinds)

    def test_csp_allows_video_archive_media(self):
        req = urllib.request.Request(self.url + '/')
        with self.anonymous().open(req, timeout=5) as r:
            csp = r.headers.get('Content-Security-Policy', '')
        self.assertIn('media-src', csp)
        self.assertIn('video.rosoncoweb.ru', csp)

    def test_malformed_map_is_ignored(self):
        mat = Materials(json.loads(self.data.read_text()))
        mat.set_suggestions({'schema': 'other', 'videos': 'x', 'lectures': None})
        view = mat.view(DATA['modules'][0])
        self.assertEqual([v for v in view['faculty_videos']
                          if v['kind'] == 'suggested_video'], [])
