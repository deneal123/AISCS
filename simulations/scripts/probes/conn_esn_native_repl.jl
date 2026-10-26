# Extra diagnostic after the preserved CLI failure. The author's script uses
# interactive global-loop scoping; execute the same source with REPL.softscope.
using Random, REPL, LinearAlgebra, JSON, SHA
if isfile("/work/fontconfig.conf")
    ENV["FONTCONFIG_FILE"] = "/work/fontconfig.conf"
end
include("/work/source/src/Reservoirs_src.jl")
include("/work/source/src/ReservoirTasks.jl")
include("/work/source/src/ConnectomeFunctions.jl")
using Plots
BLAS.set_num_threads(4)
Random.seed!(1)
script = "/work/source/run/task1_memorycapacity.jl"
seconds = @elapsed Base.include(REPL.softscope, Main, script)
@assert size(final_outputs) == (200, 1000)
@assert all(isfinite, final_outputs) && isfinite(memory_capacity)
@assert size(reservoir_state_train) == (300, 4000)
mkpath("/work/export")
savefig(memoryplot, "/work/export/native-memory-task.png")
savefig(memoryplot, "/work/export/native-memory-task.svg")
open("/work/export/native-repl.json", "w") do io
    JSON.print(io, Dict(
        "status"=>"passed_repl_adapter",
        "scope"=>"Unmodified authored random-reservoir script under REPL.softscope; distinct from the failed noninteractive CLI and from authored connectome matrices",
        "seed"=>1, "neurons"=>300, "train_steps"=>4000, "test_steps"=>1000,
        "memory_lags"=>200, "memory_capacity"=>memory_capacity,
        "script_seconds"=>seconds, "finite_outputs"=>true,
        "script_sha256"=>bytes2hex(sha256(read(script))),
        "time_unit"=>"discrete model step, not milliseconds",
        "biological_validation"=>false,
    ), 2)
end
