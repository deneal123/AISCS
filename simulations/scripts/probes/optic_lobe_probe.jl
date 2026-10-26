if isfile("/work/fontconfig.conf")
    ENV["FONTCONFIG_FILE"] = "/work/fontconfig.conf"
end
using OpticLobe
using JSON, Random, SparseArrays, LinearAlgebra, Luxor, ColorSchemes

out = "/work/exports/optic-lobe"
mkpath(out)
mode = isempty(ARGS) ? "smoke" : ARGS[1]
n = length(ind2id)
@assert size(W) == (n, n)
@assert length(unique(ind2id)) == n
@assert all(id2ind[ind2id[i]] == i for i in 1:n)
@assert all(x -> isfinite(x) && x >= 0, nonzeros(W.array))
@assert all(iszero, diag(W.array))
@assert OpticLobe.default_synapses == "Princeton"
stats = Dict(
    "mode" => mode, "neurons" => n, "matrix_size" => collect(size(W)),
    "nonzero_pairs" => count(!iszero, nonzeros(W.array)), "synapses" => sum(W),
    "intrinsic_types" => length(intrinsictypes), "boundary_types" => length(boundarytypes),
    "all_types" => length(alltypes), "mapped_columns" => count(!ismissing, pq2column),
    "units" => Dict("W" => "synapse counts", "coordinates" => "hexagonal lattice indices"),
    "dynamic_simulation" => false, "biological_validation" => false,
    "t1_root_ids" => string.(ind2id[findall(x -> !ismissing(x) && x == "T1", ind2type)]),
)
if mode == "full"
    morphology = Dict()
    for (label, quantity) in [("length_um", cell_length), ("area_um2", cell_area), ("volume_um3", cell_volume)]
        valid = collect(skipmissing(quantity.array))
        @assert length(quantity) == n
        @assert all(x -> isfinite(x) && x >= 0, valid)
        morphology[label] = Dict("available" => length(valid), "missing" => n - length(valid),
            "range" => [minimum(valid), maximum(valid)])
    end
    stats["morphology"] = morphology
    # Independently check the package's cell-to-type aggregation on real cells.
    checked_pairs = [("Tm1", "TmY4"), ("Tm1", "Pm03"), ("T1", "Tm1")]
    checks = []
    for (pre, post) in checked_pairs
        # Wtt includes both hemispheres; type2ids defaults to the right side.
        pre_indices = findall(x -> !ismissing(x) && x == pre, ind2type)
        post_indices = findall(x -> !ismissing(x) && x == post, ind2type)
        direct = sum(W.array[pre_indices, post_indices])
        @assert direct == Wtt[pre, post]
        push!(checks, Dict("pre" => pre, "post" => post, "cell_sum" => direct, "type_sum" => Wtt[pre, post]))
    end
    # Repetition tests sampling and analysis, not stochastic neuronal dynamics.
    samples = []
    for seed in [1, 2, 3, 1]
        rng = MersenneTwister(seed)
        inds = sort(randperm(rng, n)[1:32])
        push!(samples, Dict("seed" => seed, "ids" => string.(ind2id[inds]),
            "outgoing_synapses" => vec(sum(W.array[inds, :], dims=2)),
            "incoming_synapses" => vec(sum(W.array[:, inds], dims=1))))
    end
    @assert samples[1] == samples[4]
    stats["aggregation_checks"] = checks
    normalized = OpticLobe.Wback.array
    column_sums = vec(sum(normalized, dims=1))
    @assert all(isfinite, nonzeros(normalized))
    @assert all(x -> isapprox(x, 0; atol=1e-5) || isapprox(x, 1; atol=1e-5), column_sums)
    stats["backward_normalization_verified"] = true
    stats["seeded_sampling"] = samples
    stats["seed1_exact_repeat"] = true
    stats["repeat_seed_equal"] = true

    # Export the real intrinsic-type matrix for downstream inspection.
    selected = intrinsictypes
    open(joinpath(out, "intrinsic-connectivity.csv"), "w") do io
        println(io, "pre_type," * join(selected, ","))
        for pre in selected
            println(io, pre * "," * join([Wtt[pre, post] for post in selected], ","))
        end
    end
    ids = type2ids("Tm1")
    root = first(ids)
    weights = collect(Wct[Name(root), visualtypes])
    targets = sortperm(weights, rev=true)[1:12]
    stats["example_root_id"] = string(root)
    stats["example_top_targets"] = [Dict("type" => visualtypes[i], "synapses" => weights[i]) for i in targets]

    # Native Luxor/hexgraphics rendering on the true v783 column mask.
    grating = sine_grating([0.18, -0.06], 0.0; amplitude=1.0)
    vals = collect(skipmissing(vec(grating)))
    @assert all(isfinite, vals) && all(abs.(vals) .<= 1.0 + eps())
    @assert size(grating) == size(pq2column)
    for ext in ["png", "svg"]
        Drawing(1000, 800, joinpath(out, "native-hex-grating." * ext))
        origin()
        background("white")
        gsave()
        translate(0, 25)
        rect2hex(eyeheat((grating .+ 1) ./ 2, 1.0; cmap=ColorSchemes.viridis); hexelsize=10)
        grestore()
        setcolor("black")
        fontsize(22)
        text("OpticLobe.jl: visual input on FlyWire v783 eye columns", Point(0, -355), halign=:center)
        fontsize(17)
        text("Synthetic sine-grating stimulus; not a neuronal response", Point(0, 365), halign=:center)
        finish()
    end
    stats["stimulus_shape"] = collect(size(grating))
    stats["stimulus_range"] = [minimum(vals), maximum(vals)]
    stats["grating_is_input_not_neural_response"] = true

    paths = tracetypes(["Tm1", "T3"])
    totals = vec(sum(paths.array, dims=1))
    best = sortperm(totals, rev=true)[1:3]
    maps = inmaps(paths[:, best])
    @assert all(im -> all(isfinite, im) && all(im .>= 0), maps.array)
    @assert all(im -> sum(im) > 0, maps.array)
    mapped_ids = names(paths, 2)[best]
    labels = ["T3 " * string(id)[end-5:end] for id in mapped_ids]
    montage(maps.array; fname=joinpath(out, "native-Tm1-T3-input-maps.svg"),
        hexelsize=6, labels=labels, montagesize=(3, 1), fontsize=16)
    # Upstream montage supplies fractional pixel dimensions to Cairo for PNG.
    # Keep its SVG result and use an integer-sized canvas for a raster preview.
    Drawing(1500, 650, joinpath(out, "native-Tm1-T3-input-maps.png"))
    background("white")
    origin()
    setcolor("black")
    fontsize(24)
    text("Anatomical Tm1 input maps to three T3 cells", Point(0, -285), halign=:center)
    for (i, im) in enumerate(maps.array)
        gsave()
        translate(-500 + (i-1)*500, 15)
        rect2hex(eyehot(im); hexelsize=6)
        setcolor("black")
        fontsize(17)
        text(labels[i], Point(0, -230), halign=:center)
        grestore()
    end
    setcolor("black")
    fontsize(18)
    text("Synapse-count maps on the v783 column lattice; not measured receptive fields", Point(0, 285), halign=:center)
    finish()
    stats["input_maps"] = Dict("path" => ["Tm1", "T3"], "post_root_ids" => string.(mapped_ids),
        "map_totals" => [sum(im) for im in maps.array], "interpretation" => "anatomical input maps, not measured receptive fields")
    stats["graphics_adapter"] = "Native montage SVG; PNG preview uses an integer-sized Luxor canvas to avoid upstream fractional-pixel InexactError"
end
open(joinpath(out, mode * "-result.json"), "w") do io
    JSON.print(io, stats, 2)
end
println("SIM-010 ", mode, " passed; ", n, " neurons; ", sum(W), " synapses")
