using LinearAlgebra, Random, Statistics, SparseArrays, JSON, SHA, CSV, DataFrames
BLAS.set_num_threads(4)
if isfile("/work/fontconfig.conf")
    ENV["FONTCONFIG_FILE"] = "/work/fontconfig.conf"
end
include("/work/source/src/Reservoirs_src.jl")
include("/work/source/src/ReservoirTasks.jl")
include("/work/source/src/ConnectomeFunctions.jl")
using .Reservoirs_src, .ReservoirTasks, .ConnectomeFunctions
using Plots

out = abspath(get(ENV,"ASPA_CONN_ESN_EXPORT_DIR","/work/export"))
startswith(out,"/work/") || error("Export must remain inside the run")
mkpath(out)
mode = isempty(ARGS) ? "smoke" : ARGS[1]
function save(name, value)
    open(joinpath(out, name), "w") do io
        JSON.print(io, value, 2)
    end
end
function state_probe(W, label; example=false)
    Random.seed!(1)
    n = size(W,1)
    Win = Reservoirs_src.create_input_weights(1, n, 0.02)
    u = rand(512) .- 0.5
    function rollout(input_weights)
        current = zeros(n)
        trace = zeros(n,length(u))
        for t in eachindex(u)
            current = Reservoirs_src.update_reservoir_state(W, input_weights, current, u[t], 1.0)
            trace[:,t] = vec(current)
        end
        return trace
    end
    history = rollout(Win)
    @assert all(isfinite, history) && maximum(abs.(history)) <= 1
    @assert history == rollout(Win)
    @assert all(iszero, rollout(zeros(n,1)))
    @assert any(!iszero, history)
    @assert history[:,1] == vec(Reservoirs_src.update_reservoir_state(W, Win, zeros(n), u[1], 1.0))
    frame = DataFrame(permutedims(history), :auto)
    insertcols!(frame, 1, :step=>collect(eachindex(u)), :input=>u)
    CSV.write(joinpath(out, label * "-states.csv"), frame)
    if example
        p1 = plot(u; ylabel="Input (abstract)", legend=false, title="Authored larval ESN: driven-state diagnostic")
        p2 = plot(permutedims(history[1:3,:]); ylabel="ESN activation", label=["unit 1" "unit 2" "unit 3"])
        p3 = heatmap(history[1:min(n,40),:]; xlabel="Model step, not milliseconds", ylabel="Unit index", colorbar_title="activation")
        figure = plot(p1,p2,p3; layout=(3,1), size=(1200,900), margin=6 * Plots.PlotMeasures.mm)
        savefig(figure, joinpath(out,"reservoir-states.png"))
        savefig(figure, joinpath(out,"reservoir-states.svg"))
    end
    return Dict("steps"=>512, "units"=>n, "reset_repeat_equal"=>true, "zero_input_weights_quiescent"=>true, "driven_state_nonzero"=>true, "first_step_matches_native_update"=>true, "state_unit"=>"dimensionless ESN activation, not membrane potential", "file"=>label * "-states.csv")
end
if mode == "native"
    # Actual authored random-reservoir script, with its original sizes/loops.
    include("/work/source/run/task1_memorycapacity.jl")
elseif mode == "smoke"
    Random.seed!(1)
    W = Reservoirs_src.create_reservoir(20, 0.3, 0.9)
    @assert size(W) == (20,20) && all(isfinite, W)
    @assert isapprox(maximum(abs.(eigvals(Matrix(W)))), 0.9; atol=1e-10)
    Win = Reservoirs_src.create_input_weights(1, 20, 0.02)
    state = Reservoirs_src.update_reservoir_state(W, Win, zeros(20), 0.3, 1.0)
    @assert length(state) == 20 && all(isfinite, state)
    @assert maximum(abs.(state)) <= 1
    zero_state = Reservoirs_src.update_reservoir_state(W, zeros(20,1), zeros(20), 0.3, 1.0)
    @assert all(iszero, zero_state)
    held_state = Reservoirs_src.update_reservoir_state(W, Win, zeros(20), 0.3, 0.0)
    @assert all(iszero, held_state)
    X = randn(5,100); Y = randn(2,100)
    readout = Reservoirs_src.train_output_weights(X, Y, 1e-6)
    @assert size(readout) == (5,2) && all(isfinite, readout)
    bad_X = copy(X); bad_X[1,1] = NaN
    fallback = Reservoirs_src.train_output_weights(bad_X, Y, 1e-6)
    native_export = try
        Reservoirs_src.save_data([1.0 2.0; 3.0 4.0], "aspa_probe", "aspa_probe")
        Dict("status"=>"succeeded")
    catch e
        Dict("status"=>"failed", "exception"=>sprint(showerror,e))
    end
    include("/work/source/run/cfg_model.jl")
    config_checks = []
    for seed in 1:10
        Random.seed!(seed)
        configured = generate_cfg_network([2,2,2], [2,2,2])
        push!(config_checks, Dict("seed"=>seed, "requested_edges"=>6,
            "retained_edges"=>sum(configured), "row_degrees"=>vec(sum(configured,dims=2)),
            "column_degrees"=>vec(sum(configured,dims=1))))
    end
    save("configuration-check.json", Dict("scope"=>"adversarial software fixture for exact degree preservation, not an author data reproduction", "cases"=>config_checks, "all_degrees_preserved"=>all(x["retained_edges"]==6 for x in config_checks)))
    save("smoke.json", Dict("status"=>"passed_valid_input_checks", "spectral_radius"=>0.9, "state_shape"=>collect(size(state)), "readout_shape"=>collect(size(readout)), "invalid_input_fallback_shape"=>collect(size(fallback)), "invalid_fallback_matches_normal_shape"=>size(fallback)==size(readout), "native_save_data"=>native_export, "scope"=>"explicit numerical fixture, not connectome; invalid input and native export diagnosed separately"))
else
    manifest = JSON.parsefile("/work/conn-esn-inputs.json")
    results = []
    timings = []
    for item in manifest["inputs"]
        path = joinpath("/work", item["file"])
        @assert bytes2hex(sha256(read(path))) == item["sha256"]
        header = split(readline(path), ',')
        @assert header == ["x$i" for i in 1:length(header)]
        W = Matrix{Float64}(CSV.read(path, DataFrame))
        @assert size(W,1) == size(W,2) && all(isfinite, W)
        println("ESN matrix ", item["file"], " size ", size(W)); flush(stdout)
        runs = []
        for seed in [1,2,3,1]
            Random.seed!(seed)
            measured = @timed ReservoirTasks.res_performance_memory([W], 1, 0.02, 1e-6, 1.0)
            performance, error = measured.value
            push!(timings, Dict("file"=>item["file"], "seed"=>seed,
                "model_steps"=>5000, "seconds"=>measured.time,
                "allocated_bytes"=>measured.bytes,
                "task_steps_per_wall_second"=>5000 / measured.time))
            @assert length(performance) == length(error) == 1
            @assert all(isfinite, performance) && all(isfinite, error)
            push!(runs, Dict("seed"=>seed, "memory_capacity"=>only(performance), "nrmse"=>only(error)))
            println(item["file"], " seed ", seed, " MC ", performance, " NRMSE ", error); flush(stdout)
        end
        @assert runs[1] == runs[4]
        label = replace(item["file"], "inputs/"=>"", ".csv"=>"", "/"=>"-")
        states = state_probe(W, label; example=item["file"]=="inputs/larva/connectome.csv")
        push!(results, Dict("file"=>item["file"], "nodes"=>size(W,1), "nonzero_weights"=>count(!iszero,W), "density"=>count(!iszero,W)/length(W), "runs"=>runs, "state_diagnostic"=>states))
        save("functional-partial.json", Dict("results"=>results, "scope"=>"author ESN matrices and native memory task; not full paper replication"))
        save("performance-timing.json", Dict("scope"=>"whole native memory task: 4000 train and 1000 test updates, readout fitting and scoring; first call may include JIT, not pure integration throughput", "runs"=>timings))
    end
    save("functional-checks.json", Dict("results"=>results, "repeat_seed_equal"=>true, "seeds"=>[1,2,3,1], "time_unit"=>"discrete model step, not milliseconds", "biological_validation"=>false, "scope"=>"six authored matrices, first initialization of first subnetwork; native task 4000 train/1000 test and 100 lags; no inferential topology ranking"))
    labels = [replace(x["file"], "inputs/"=>"", ".csv"=>"") for x in results]
    vals = [x["runs"][1]["memory_capacity"] for x in results]
    p = bar(labels, vals; ylabel="Memory capacity (seed 1)", legend=false, xrotation=30,
            title="Authored ESN weights: illustrative native memory task\nOne matrix per topology/stage; not a replicated topology comparison", size=(1200,600), margin=8 * Plots.PlotMeasures.mm)
    savefig(p, joinpath(out,"memory-capacity.png"))
    savefig(p, joinpath(out,"memory-capacity.svg"))
    if mode == "full"
        child = addenv(`$(Base.julia_cmd()) --project=. /work/probes/conn_esn_probe.jl replay`,
                       "ASPA_CONN_ESN_EXPORT_DIR"=>"/work/replay-export")
        elapsed = @elapsed run(child)
        first_result = JSON.parsefile(joinpath(out,"functional-checks.json"))
        repeated_result = JSON.parsefile("/work/replay-export/functional-checks.json")
        @assert first_result == repeated_result
        comparisons = []
        for item in first_result["results"]
            name = item["state_diagnostic"]["file"]
            first_hash = bytes2hex(sha256(read(joinpath(out,name))))
            repeat_hash = bytes2hex(sha256(read(joinpath("/work/replay-export",name))))
            @assert first_hash == repeat_hash
            push!(comparisons,Dict("file"=>name,"first_sha256"=>first_hash,"repeat_sha256"=>repeat_hash))
        end
        save("independent-replay.json",Dict("status"=>"passed","repeat_content_equal"=>true,
            "separate_process"=>true,"seconds"=>elapsed,"state_csv_comparisons"=>comparisons))
    end
end
