"""Regressions found with a real local tutor; synthetic lessons and questions."""

from types import SimpleNamespace

from agent_core.engine.live_flows import nearest_lesson
from agent_core.retrieval.index import KnowledgeIndex


def lesson(index, subject, level, title, text):
    record = f"les.{subject}.{level}.test.lesson"
    index.add({"pack_id": f"pack.{subject}.{level}", "version": "1.0.0", "subject": subject, "level": level},
              {"search_fts": [{"id": record + "#1", "kind": "lesson", "record_id": record,
                               "title": title, "text": text, "kc_ids": [], "topic_ids": []}]})


def tutor(index, question, subject="physics", level="O", diagnosed=None):
    return SimpleNamespace(knowledge=SimpleNamespace(index=index),
                           state=SimpleNamespace(problem=SimpleNamespace(statement=question),
                                                 subject=subject, level=level),
                           diagnosis=SimpleNamespace(output={"subject": diagnosed}) if diagnosed else None)


def test_fallback_lesson_stays_in_subject_and_level():
    index = KnowledgeIndex()
    lesson(index, "mth", "o", "Gradient and the equation of a line", "A ball thrown straight up rises high.")
    lesson(index, "phy", "a", "Advanced motion", "A ball thrown straight up rises high.")
    lesson(index, "phy", "o", "Vertical motion", "A thrown ball moves upwards under gravity.")
    found = nearest_lesson(tutor(index, "A ball is thrown straight up. How high does it rise?"))
    assert found is not None and found["lesson_id"] == "les.phy.o.test.lesson"
    assert found["cite"].startswith("pack.phy.o@1.0.0:")


def test_fallback_does_not_cite_another_subject_when_pack_missing():
    index = KnowledgeIndex()
    lesson(index, "phy", "o", "Motion", "A cell moves upwards.")
    assert nearest_lesson(tutor(index, "A cell divides. How many cells?", diagnosed="biology")) is None


def test_fallback_does_not_match_only_question_boilerplate_or_quantities():
    index = KnowledgeIndex()
    lesson(index, "phy", "o", "Unrelated lesson", "Please show me step by step how to use 14 m and 9.8 s.")
    question = "A ball is thrown upwards at 14 m/s. Take g = 9.8 m/s². Please guide me through it step by step."
    assert nearest_lesson(tutor(index, question)) is None


def test_fallback_without_a_relevant_lesson_is_empty():
    index = KnowledgeIndex()
    lesson(index, "phy", "o", "Current and resistance", "Electric current flows in a circuit.")
    assert nearest_lesson(tutor(index, "A ball rises upwards under gravity.")) is None


def test_specialist_timeout_cancels_the_model_call(tmp_path):
    import asyncio

    from engine_harness import make_engine

    async def scenario():
        engine, _ = await make_engine(tmp_path, {}, worker=False)
        engine.deps.assets.roles["solver"].meta["limits"]["wall_clock_s"] = 0.03
        stopped = asyncio.Event()

        async def slow(*args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        engine._call = slow
        turn = engine._begin("ask")
        result = await asyncio.wait_for(engine.delegate("solver", "Synthetic task", turn), 1)
        assert result["stop_reason"] == "timeout" and result["schema_valid"] is False
        assert stopped.is_set()

    asyncio.run(scenario())


def test_specialist_stops_repeating_malformed_calls(tmp_path):
    import asyncio

    from engine_harness import make_engine, reply

    async def scenario():
        bad = reply("", [("bad", "nonexistent_math_tool", {"x": "1"})])
        engine, provider = await make_engine(tmp_path, {"solver": [bad] * 12}, worker=False)
        turn = engine._begin("ask")
        from agent_core.engine import turn_scope

        with turn_scope(turn.turn_id):
            result = await engine.delegate("solver", "Synthetic task", turn)
        assert result["stop_reason"] == "tool_failures" and result["schema_valid"] is False
        assert len(provider.requests) == engine.deps.settings.guard_strike_turns

    asyncio.run(scenario())


def test_maths_quantity_error_explains_recovery_and_corrected_call_is_exact():
    from test_m12b_physics import call

    bad = call("math_solve", {"equations": ["v^2=u^2+2*a*s"], "unknowns": ["s"],
                              "quantities": {"s": "height"}, "units": {"s": "m"}})
    assert "error" in bad
    assert "known numeric values with units" in bad["error"]["message"]
    assert "unknown symbols only in unknowns" in bad["error"]["message"]
    result = call("math_solve", {"equations": ["v^2=u^2+2*a*s"], "unknowns": ["s"],
                                 "quantities": {"u": "14 m/s", "v": "0 m/s", "a": "-9.8 m/s^2"},
                                 "units": {"s": "m"}, "positive_direction": "up"})["result"]
    assert result["value"]["solutions"][0]["s"]["text"] == "10"
    assert result["value"]["solutions"][0]["s"]["unit"] == "m"
    assert result["check"]["confidence"] == "proved"


def test_numbered_candidates_decode_diagnosis_without_redundant_lookup(tmp_path, monkeypatch):
    import asyncio

    from agent_core.engine import team, turn_scope
    from engine_harness import make_engine
    from test_g114_s2_engine import diagnosis

    monkeypatch.setattr(team, "candidates", lambda *_: (["cur.phy.o.motion"], [], []))

    async def scenario():
        engine, provider = await make_engine(tmp_path, {"diagnoser": [diagnosis(topic_ref=1)]}, worker=False)
        turn = engine._begin("ask")
        with turn_scope(turn.turn_id):
            result = await team.diagnose(engine, turn, "A synthetic motion question")
        assert result is not None and result.topic_id == "cur.phy.o.motion"
        assert len(provider.requests) == 1
        assert not provider.requests[0].get("tools")

    asyncio.run(scenario())


def test_specialist_timeout_cancels_in_flight_tool(tmp_path):
    import asyncio

    from agent_core.engine import turn_scope
    from engine_harness import make_engine, reply

    async def scenario():
        engine, _ = await make_engine(tmp_path, {"solver": [reply("", [("s", "skill", {"skill_name": "test"})])]},
                                      worker=False)
        engine.deps.assets.roles["solver"].meta["limits"]["wall_clock_s"] = 0.05
        started, stopped = asyncio.Event(), asyncio.Event()

        async def slow(*args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        engine.deps.executor.host_executors["skill"] = slow
        turn = engine._begin("ask")
        with turn_scope(turn.turn_id):
            result = await asyncio.wait_for(engine.delegate("solver", "Synthetic task", turn), 1)
        assert result["stop_reason"] == "timeout"
        assert started.is_set() and stopped.is_set()

    asyncio.run(scenario())


def test_minimal_output_contract_preserves_nested_solution_fields():
    import json

    from agent_core.engine.assembly import bundled_schemas
    from agent_core.prompts.builder import output_contract
    from jsonschema import Draft202012Validator

    schema = bundled_schemas()["agents/solution-plan"]
    text = output_contract(schema, "structured", 400)
    sample = json.loads(text.split("\n", 1)[1])
    assert len(text) <= 400
    Draft202012Validator(schema).validate(sample)
    assert set(sample["steps"][0]) == set(schema["properties"]["steps"]["items"]["required"])
    assert "unit" in sample["final_answer"] and "units" not in sample["final_answer"]


def test_solver_requires_a_live_tool_until_a_check_exists(tmp_path):
    import asyncio

    from agent_core.engine import turn_scope
    from engine_harness import close, make_engine, solver_steps

    async def scenario():
        engine, provider = await make_engine(tmp_path, {"solver": solver_steps()})
        try:
            turn = engine._begin("ask")
            with turn_scope(turn.turn_id):
                result = await engine.delegate("solver", "Synthetic vertical motion question", turn)
            assert result["schema_valid"] is True
            assert provider.requests[0]["tool_choice"] == "required"
            # The plan decode keeps the same system prompt and tools, made uncallable, so a local runtime reuses
            # its cached prefix (MDL-22, D123); only the phase message after the history differs.
            assert provider.requests[1]["tool_choice"] == "none" and "response_format" in provider.requests[1]
            assert provider.requests[1]["tools"] == provider.requests[0]["tools"]
            assert provider.requests[1]["messages"][0] == provider.requests[0]["messages"][0]
            assert result["output"]["final_answer"]["check_id"] in engine.state.check_values
        finally:
            await close(engine)

    asyncio.run(scenario())


def test_constrained_plan_corrects_missing_metadata_without_accepting_wrong_values(tmp_path):
    import asyncio
    import json

    from agent_core.engine import turn_scope
    from engine_harness import close, make_engine, solver_steps

    async def scenario():
        script = solver_steps()
        complete = script[1]

        def missing_nulls(body):
            response = complete(body)
            message = response["reply"]["choices"][0]["message"]
            draft = json.loads(message["content"])
            del draft["blocked_step"], draft["blocked_reason"]
            message["content"] = json.dumps(draft)
            return response

        engine, provider = await make_engine(tmp_path, {"solver": [script[0], missing_nulls, complete]})
        try:
            turn = engine._begin("ask")
            with turn_scope(turn.turn_id):
                result = await engine.delegate("solver", "Synthetic vertical motion question", turn)
            assert result["schema_valid"] is True and len(provider.requests) == 3
            assert result["output"]["blocked_step"] is None and result["output"]["blocked_reason"] is None
            assert result["output"]["final_answer"]["check_id"] in engine.state.check_values
            wrong = json.loads(json.dumps(result))
            wrong["output"]["final_answer"]["value"] = "12"
            assert engine._verified_plan(wrong)[0] is None, "nullable metadata repair cannot certify a wrong answer"
        finally:
            await close(engine)

    asyncio.run(scenario())

def test_method_request_preserves_givens_without_grading_or_board(tmp_path):
    import asyncio

    from agent_core.engine.pedagogy import asks_method
    from agent_core.engine.state import Problem
    from engine_harness import close, make_engine
    from engine_harness import tutor as coach

    text = ('The initial velocity is 14 m/s upwards. Acceleration is -9.8 m/s², '
            'and at the highest point velocity is zero. Which equation can I use?')
    assert asks_method(text)
    assert not asks_method('s = 12 m. Which equation can I use?')
    assert not asks_method('Is 0 = 14^2 + 2(9.8)s correct?')

    async def scenario():
        engine, provider = await make_engine(tmp_path, {'coach': [coach('Which quantities should the equation link?')]})
        try:
            engine.state.problem = Problem('prb_test', 'Find the maximum height.', 'prb_test#statement')
            result = await engine.student_turn(text)
            assert result.status == 'complete'
            assert engine.state.attempts == {} and engine.state.board.steps == []
            assert text in engine.state.student_lines
            assert engine.state.transcript[-2]['kind'] == 'chat'
            assert all(not request.get('tools') for request in provider.requests)
            schema = provider.requests[-1]['response_format']['json_schema']['schema']
            assert schema['properties']['board']['maxItems'] == 0
            assert schema['properties']['visual']['maxItems'] == 0
            assert schema['properties']['card']['type'] == 'null'
            assert engine.deps.bundled_schemas['agents/tutor-turn']['properties']['board']['maxItems'] == 6
        finally:
            await close(engine)

    asyncio.run(scenario())


def test_guided_equations_each_receive_live_worker_checks(tmp_path):
    import asyncio
    from fractions import Fraction

    from agent_core.engine import turn_scope
    from agent_core.engine.state import Plan, PlanStep, Problem
    from engine_harness import close, make_engine

    async def scenario():
        engine, provider = await make_engine(tmp_path, {})
        try:
            engine.state.problem = Problem('prb_test', 'A ball rises at 14 m/s; g = 9.8 m/s².', 'prb_test#statement')
            engine.state.plan = Plan([PlanStep(1, 'v^2 = u^2 + 2as', None, None, None),
                                      PlanStep(2, '0 = 14^2 - 2(9.8)s', None, None, None),
                                      PlanStep(3, r's = 10\text{ m}', '10', 'm', 'chk_test')],
                                     '10', 'm', 'chk_test', final_latex='s = 10 m')
            engine.state.check_values['chk_test'] = [Fraction(10)]
            turn = engine._begin('answer')
            with turn_scope(turn.turn_id):
                verdict = await engine._check_attempt(turn, 'v^2 = u^2 + 2as, so 0 = 14^2 - 2(9.8)s')
            assert verdict == 'correct' and len(engine.state.board.steps) == 2
            assert all(s.status == 'correct' and s.check_id in engine.state.check_values
                       for s in engine.state.board.steps)
            assert engine.state.step == 3 and not engine.state.solved
            assert provider.requests == []
            assert all(row['status'] == 'ok' for row in turn.tools.log)
            for text in ['0 = 14^2 + 2(9.8)s', '0 = 196 - 19.6*s + 0.0098']:
                with turn_scope(turn.turn_id):
                    assert await engine._check_attempt(turn, text) == 'incorrect'
                assert not engine.state.solved
            with turn_scope(turn.turn_id):
                verdict = await engine._check_attempt(turn, 'v^2 = u^2 - 2as, so 0 = 14^2 - 2(9.8)s')
            assert verdict != 'correct' and engine.state.board.steps[-2].status != 'correct'
            with turn_scope(turn.turn_id):
                verdict = await engine._check_attempt(turn, 'v^2 = u^2 - 2as, so s = 10 m')
            assert verdict != 'correct' and not engine.state.solved
            with turn_scope(turn.turn_id):
                verdict = await engine._check_attempt(turn, '0 = 14^2 - 19.6*s, so s = 10 m')
            assert verdict == 'correct' and engine.state.solved
        finally:
            await close(engine)

    asyncio.run(scenario())


def test_short_tutor_contract_is_valid_and_leaves_ui_optional():
    import json

    from agent_core.contracts import validator
    from agent_core.prompts.builder import output_contract
    from engine_harness import bundled_schemas

    schema = bundled_schemas()['agents/tutor-turn']
    contract = output_contract(schema, 'structured', 1000)
    draft = json.loads(contract.split('\n', 1)[1])
    assert draft['say_spoken'] is None and draft['board'] == [] and draft['visual'] == [] and draft['card'] is None
    assert list(validator('agents/tutor-turn').iter_errors(draft)) == []


def test_solver_can_reopen_tools_for_additional_checks(tmp_path):
    import asyncio
    import json

    from agent_core.engine import turn_scope
    from engine_harness import close, last_check_id, make_engine, reply, solver_steps

    async def scenario():
        script = solver_steps()
        answer_check = None

        def needs_more(body):
            nonlocal answer_check
            answer_check = last_check_id(body)
            return reply(json.dumps({'status': 'blocked', 'method_summary': 'Verify the squared initial speed.',
                                     'steps': [{'index': 1, 'latex': '14^2', 'reason': 'Check the square',
                                                'check_id': None, 'kc_ref': None, 'value': None, 'unit': None}],
                                     'final_answer': None, 'blocked_step': 1,
                                     'blocked_reason': 'needs_tools: evaluate the square of the initial speed'}))

        def final(body):
            result = script[1](body)
            draft = json.loads(result['reply']['choices'][0]['message']['content'])
            draft['final_answer']['check_id'] = answer_check
            draft['steps'][-1]['check_id'] = answer_check
            return reply(json.dumps(draft))

        engine, provider = await make_engine(tmp_path, {'solver': [script[0], needs_more,
            reply('', [('extra', 'math_check_equivalence', {'a': '14^2', 'b': '196'})]), final]})
        from dataclasses import replace

        skill = engine.deps.assets.skills.skills['phy-o-motion']
        skill = replace(skill, meta={**skill.meta, 'requires_tools': ['math_solve', 'python_run']})
        engine._teaching_skill = lambda: skill
        try:
            turn = engine._begin('ask')
            with turn_scope(turn.turn_id):
                result = await engine.delegate('solver', 'Synthetic calculation requiring a further check', turn)
            assert result['schema_valid'] and result['output']['status'] == 'complete'
            assert engine._verified_plan(result)[0] is not None
            # Tools stay in every request for the cached prefix (D123); the plan decodes make them uncallable.
            assert all(r.get('tools') for r in provider.requests)
            assert [r.get('tool_choice') == 'none' for r in provider.requests] == [False, True, False, True]
            first = {t['function']['name'] for t in provider.requests[0]['tools']}
            expanded = {t['function']['name'] for t in provider.requests[2]['tools']}
            assert first == {'math_solve', 'math_evaluate', 'units_convert', 'units_check_dimensions'}
            assert 'math_check_equivalence' not in first and 'math_check_equivalence' in expanded
            assert 'python_run' not in expanded, 'a teaching skill cannot widen role grants'
        finally:
            await close(engine)

    asyncio.run(scenario())


def test_text_only_method_reply_still_withholds_the_checked_answer(tmp_path):
    import asyncio
    from fractions import Fraction

    from agent_core.engine.state import Plan, PlanStep, Problem
    from engine_harness import close, make_engine
    from engine_harness import tutor as response

    async def scenario():
        engine, _ = await make_engine(tmp_path, {'coach': [
            response('It rises 10 m. Which equation would you use?'),
            response('Which equation links speed, acceleration and displacement?')]}, worker=False)
        try:
            engine.state.problem = Problem('prb_test', 'Find the height for u = 14 m/s, g = 9.8 m/s².', 'prb_test#q')
            engine.state.plan = Plan([PlanStep(1, 's = 10', '10', 'm', 'chk_test')], '10', 'm', 'chk_test')
            engine.state.check_values['chk_test'] = [Fraction(10)]
            result = await engine.student_turn('Which equation can I use?')
            assert result.status == 'complete' and not result.degraded
            assert '10' not in engine.events.student_text(result.turn_id)
            gate = next(g for g in result.trace['gates'] if g['gate'] == 'no_answer_leak')
            assert gate['fired'] and gate['outcome'] == 'passed_after_nudge'
            assert not engine.state.solved and not engine.state.attempts
        finally:
            await close(engine)

    asyncio.run(scenario())


def test_solver_computes_before_plan_even_if_provider_ignores_required_tool(tmp_path):
    import asyncio

    from agent_core.engine import turn_scope
    from engine_harness import close, make_engine, reply, solver_steps

    async def scenario():
        script = solver_steps()
        engine, provider = await make_engine(tmp_path, {'solver': [reply('I would calculate the height.'), *script]})
        try:
            turn = engine._begin('ask')
            with turn_scope(turn.turn_id):
                result = await engine.delegate('solver', 'Synthetic vertical-motion calculation', turn)
            assert result['schema_valid'] and engine._verified_plan(result)[0] is not None
            assert len(provider.requests) == 3
            for request in provider.requests[:2]:
                assert request['tool_choice'] == 'required' and 'response_format' not in request
                assert 'Current phase: computation' in request['messages'][-1]['content']
            systems = {r['messages'][0]['content'] for r in provider.requests}
            assert len(systems) == 1 and 'Current phase: computation' not in systems.pop()
            last = provider.requests[-1]
            assert last['tool_choice'] == 'none' and last['tools'] and 'response_format' in last
        finally:
            await close(engine)

    asyncio.run(scenario())


def test_solver_refusal_to_compute_fails_closed_without_plan_decode(tmp_path):
    import asyncio

    from agent_core.engine import turn_scope
    from engine_harness import make_engine, reply

    async def scenario():
        engine, provider = await make_engine(tmp_path, {'solver': [reply('The answer is 10 m.')] * 2}, worker=False)
        turn = engine._begin('ask')
        with turn_scope(turn.turn_id):
            result = await engine.delegate('solver', 'Synthetic calculation', turn)
        assert result['stop_reason'] == 'tool_failures' and not result['schema_valid']
        assert result['output'] is None and len(provider.requests) == 2
        assert all('response_format' not in r for r in provider.requests)

    asyncio.run(scenario())


def test_parse_check_does_not_replace_the_required_calculation(tmp_path):
    import asyncio

    from agent_core.engine import turn_scope
    from engine_harness import close, make_engine, reply, solver_steps

    async def scenario():
        engine, provider = await make_engine(tmp_path, {'solver': [
            reply('', [('parse', 'math_parse', {'text': '10'})]), *solver_steps()]})
        try:
            turn = engine._begin('ask')
            with turn_scope(turn.turn_id):
                result = await engine.delegate('solver', 'Synthetic calculation', turn)
            assert result['schema_valid']
            assert provider.requests[1]['tool_choice'] == 'required'
            parse_check = result['tool_calls'][0]['check_id']
            assert engine.state.check_values[parse_check] == []
            assert len(provider.requests) == 3 and engine._verified_plan(result)[0] is not None
        finally:
            await close(engine)

    asyncio.run(scenario())


def test_non_ui_contract_examples_do_not_teach_empty_fact_arrays():
    import json

    from agent_core.prompts.builder import output_contract

    schema = {'type': 'object', 'required': ['knowns'], 'properties': {'knowns': {
        'type': 'array', 'items': {'type': 'object', 'required': ['value'],
                                 'properties': {'value': {'type': 'string'}}}}}}
    example = json.loads(output_contract(schema, 'structured', 400).split('\n', 1)[1])
    assert example['knowns'] == [{'value': '...'}]


def test_motion_formula_uses_authored_reference_when_plan_omits_or_misstates_it(tmp_path):
    import asyncio
    from fractions import Fraction

    from agent_core.engine import turn_scope
    from agent_core.engine.state import Plan, PlanStep, Problem
    from engine_harness import close, make_engine

    async def scenario():
        engine, _ = await make_engine(tmp_path, {})
        engine._teaching_skill = lambda: engine.deps.assets.skills.skills['phy-o-motion']
        engine.state.problem = Problem('prb_test', 'A ball rises at 14 m/s; g = 9.8 m/s².', 'prb_test#statement')
        engine.state.plan = Plan([PlanStep(1, 'u = 14 m/s, a = -9.8 m/s², v = 0 m/s', None, None, None),
                                  PlanStep(2, '0 = 14^2 - 2(9.8)s', None, None, None),
                                  PlanStep(3, r's = \frac{14^2}{19.6} = 10', '10', 'm', 'chk_test')],
                                 '10', 'm', 'chk_test', final_latex='s = 10 m')
        engine.state.check_values['chk_test'] = [Fraction(10)]
        try:
            turn = engine._begin('answer')
            with turn_scope(turn.turn_id):
                result = await engine._check_attempt(turn, 'v^2 = u^2 + 2as, so 0 = 14^2 - 2(9.8)s')
            assert result == 'correct' and all(s.status == 'correct' for s in engine.state.board.steps)
            engine.state.plan.steps[1].latex = '0 = 14^2 - 2(9.8)h'
            engine.state.plan.steps[2].latex = 'h = 10'
            engine.state.plan.final_latex = '10'
            engine.state.plan.steps[0].latex = r'v_i = 14\text{ m/s}, g = 9.8\text{ m/s}^2'
            engine.state.plan.steps[2].latex = '0 = 196 - 19.6h'
            with turn_scope(turn.turn_id):
                assert await engine._check_attempt(turn, '0 = 14^2 - 2(9.8)s') == 'correct'
            engine.state.board.knowns = [{'symbol': 's', 'value': '14', 'unit': 'm'}]
            with turn_scope(turn.turn_id):
                assert await engine._check_attempt(turn, '0 = 14^2 - 2(9.8)s') != 'correct'
            engine.state.board.knowns = []
            assert all(row['status'] == 'ok' for row in turn.tools.log), 'chained plan equations are not parser inputs'
            engine.state.plan.steps[0].latex = 'v^2 = u^2 - 2as'
            with turn_scope(turn.turn_id):
                assert await engine._check_attempt(turn, 'v^2 = u^2 - 2as') != 'correct'
        finally:
            await close(engine)

    asyncio.run(scenario())


def test_schema_compilers_preserve_properties_named_like_schema_keywords():
    from agent_core.providers.openai_compat import grammar_friendly
    from agent_core.router.structured import decode_schema
    from jsonschema import Draft202012Validator

    names = ['title', 'description', 'pattern', 'maxLength', 'default', 'examples', 'format', '$ref']
    schema = {'title': 'Annotation only', 'type': 'object', 'additionalProperties': False,
              'required': names, 'properties': {name: {'type': 'string', 'maxLength': 20} for name in names}}
    for compile_schema in (decode_schema, grammar_friendly):
        result = compile_schema(schema)
        assert set(result['properties']) == set(names)
        Draft202012Validator(result).validate({name: 'value' for name in names})
    assert 'title' not in decode_schema(schema), 'schema annotations are still removed'


def test_worker_provenance_excludes_check_identifiers_and_warning_bounds(tmp_path):
    import asyncio
    import json
    from fractions import Fraction

    from agent_core.engine import turn_scope
    from agent_core.engine.slice import run_tool
    from engine_harness import close, make_engine

    async def scenario():
        engine, _ = await make_engine(tmp_path, {})
        try:
            original = engine.deps.executor.run_one

            async def wrapped(*args, **kwargs):
                result = await original(*args, **kwargs)
                if result['status'] == 'ok' and result['meta'].get('checks'):
                    cid = 'chk_987654321'
                    result['meta']['checks'][0]['check_id'] = cid
                    result['output'] = json.dumps({'check_id': cid, 'value': result['data']['value'],
                                                   'warning': 'An unrelated bound is 7654321.'})
                return result

            engine.deps.executor.run_one = wrapped
            turn = engine._begin('ask')
            with turn_scope(turn.turn_id):
                value, check = await run_tool(engine, turn, 'math_evaluate', {'expression': '2+3'})
            assert value and check == 'chk_987654321'
            assert Fraction(5) in engine.state.check_values[check]
            assert Fraction(987654321) not in engine.state.provenance()
            assert Fraction(7654321) not in engine.state.provenance()
        finally:
            await close(engine)

    asyncio.run(scenario())


def test_numeric_proof_does_not_promote_symbolic_coefficients_or_fraction_components():
    from fractions import Fraction

    from agent_core.engine.toolround import _checked_numbers

    assert _checked_numbers({'solutions': [{'x987654': {'text': '10*f', 'decimal': None}}]}) == []
    values = _checked_numbers({'solutions': [{'x987654': {
        'text': '10/3', 'decimal': '3.33333', 'numerator': 10, 'denominator': 3}}]})
    assert Fraction(10, 3) in values
    assert Fraction(10) not in values and Fraction(3) not in values and Fraction(987654) not in values
    assert _checked_numbers(True) == [] and _checked_numbers('1e999999999') == []
    assert _checked_numbers('1 2') == [] and _checked_numbers('1 / 2') == [Fraction(1, 2)]
