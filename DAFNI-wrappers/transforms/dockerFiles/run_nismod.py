import os
import yaml
import json
from pathlib import Path
from extract_data import extract
from utils import run_process, is_truthy
from settings import (
    INPUT_PATH,
    NISMOD_PATH,
    RESULTS_PATH,
    TRANSPORT_ADDITIONAL_OUTPUTS_PATH,
    model_to_run,
    transforms_to_run,
    timestep,
    use_generated_scenario,
)


def extract_and_run():
    extract()

    model_run_file = NISMOD_PATH.joinpath("config/model_runs/", model_to_run + ".yml")
    if is_truthy(use_generated_scenario):
        generated_scenario = INPUT_PATH.joinpath(model_to_run + ".yml")
        generated_scenario.parent.mkdir(parents=True, exist_ok=True)
        os.link(generated_scenario, model_run_file)

    transforms_list = json.loads(transforms_to_run)
    go_to_nismod_root = "cd " + str(NISMOD_PATH)

    with open(model_run_file, "r") as f:
        model_run = yaml.safe_load(f.read())

    print("Beginning transforms run   -   ", model_run)
    run_process(go_to_nismod_root + " && smif list")
    # run_process(go_to_nismod_root + " && smif decide " + model_to_run)
    # print("Decide step finished")

    for transform in transforms_list:
        run_process(
            go_to_nismod_root
            + " && smif before_step "
            + model_to_run
            + " --model "
            + transform
        )
        print("Before step finished")
        if timestep == "":
            for t in model_run["timesteps"]:
                run_for_timestep = (
                    go_to_nismod_root
                    + " && smif step "
                    + model_to_run
                    + " --model "
                    + transform
                    + " --timestep "
                    + str(t)
                    + " --decision 0"
                )
                print("running - ", run_for_timestep)
                run_process(run_for_timestep)
                print("Run for timestep" + str(t))

        else:
            inputs_dir = INPUT_PATH.joinpath(model_to_run)
            additional_inputs_dir = INPUT_PATH.joinpath("additional/")
            if inputs_dir.exists():
                print("Copying results from previous step to results folder")
                RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
                run_process("cp -ru " + str(inputs_dir) + "/ " + str(RESULTS_PATH))
                print("Copied results")
            if additional_inputs_dir.exists():
                print("Copying results from transport step to results folder")
                TRANSPORT_ADDITIONAL_OUTPUTS_PATH.mkdir(parents=True, exist_ok=True)
                run_process("cp -ru " + str(additional_inputs_dir) + "/* " + str(TRANSPORT_ADDITIONAL_OUTPUTS_PATH))
                print("Copied transport results")

            run_for_timestep = (
                go_to_nismod_root
                + " && smif step "
                + model_to_run
                + " --model "
                + transform
                + " --timestep "
                + timestep
                + " --decision 0"
            )
            print("running - ", run_for_timestep)
            run_process(run_for_timestep)
            print("Run for timestep" + timestep)
