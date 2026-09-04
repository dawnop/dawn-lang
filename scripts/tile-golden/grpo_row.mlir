cuda_tile.module @m {
  entry @grpo_row(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>, %arg4: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 32> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %1 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<32xi32>
    %8 = iota : tile<32xi32>
    %9 = constant <i32: 0> : tile<32xi32>
    %10 = muli %8, %9 : tile<32xi32>
    %11 = addi %7, %10 : tile<32xi32>
    %12 = reshape %arg3 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %13 = broadcast %12 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %14 = offset %13, %11 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %15, %16 = load_ptr_tko weak %14 token=%0 : tile<32xptr<f64>> -> tile<32xf64>, token
    %17 = reshape %5 : tile<i32> -> tile<1xi32>
    %18 = broadcast %17 : tile<1xi32> -> tile<32xi32>
    %19 = iota : tile<32xi32>
    %20 = addi %18, %19 : tile<32xi32>
    %21 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %22 = broadcast %21 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %23 = offset %22, %20 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %24, %25 = load_ptr_tko weak %23 token=%16 : tile<32xptr<f64>> -> tile<32xf64>, token
    %26 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %27 = broadcast %26 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %28 = offset %27, %20 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %29, %30 = load_ptr_tko weak %28 token=%25 : tile<32xptr<f64>> -> tile<32xf64>, token
    %31 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %32 = broadcast %31 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %33 = offset %32, %20 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %34, %35 = load_ptr_tko weak %33 token=%30 : tile<32xptr<f64>> -> tile<32xf64>, token
    %36 = subf %24, %29 rounding<nearest_even> : tile<32xf64>
    %37 = exp %36 : tile<32xf64>
    %38 = constant <f64: 0.8> : tile<32xf64>
    %39 = maxf %37, %38 : tile<32xf64>
    %40 = constant <f64: 1.2> : tile<32xf64>
    %41 = minf %39, %40 : tile<32xf64>
    %42 = mulf %37, %15 rounding<nearest_even> : tile<32xf64>
    %43 = mulf %41, %15 rounding<nearest_even> : tile<32xf64>
    %44 = minf %42, %43 : tile<32xf64>
    %45 = subf %34, %24 rounding<nearest_even> : tile<32xf64>
    %46 = exp %45 : tile<32xf64>
    %47 = subf %46, %45 rounding<nearest_even> : tile<32xf64>
    %48 = constant <f64: 1.0> : tile<32xf64>
    %49 = subf %47, %48 rounding<nearest_even> : tile<32xf64>
    %50 = constant <f64: 0.1> : tile<32xf64>
    %51 = mulf %50, %49 rounding<nearest_even> : tile<32xf64>
    %52 = subf %44, %51 rounding<nearest_even> : tile<32xf64>
    %53 = reduce %52 dim=0 identities=[0.0 : f64] : tile<32xf64> -> tile<f64> (%54: tile<f64>, %55: tile<f64>) {
      %56 = addf %54, %55 rounding<nearest_even> : tile<f64>
      yield %56 : tile<f64>
    }
    %57 = reshape %53 : tile<f64> -> tile<1xf64>
    %58 = broadcast %57 : tile<1xf64> -> tile<1xf64>
    %59 = constant <i32: 1> : tile<i32>
    %60 = muli %1, %59 : tile<i32>
    %61 = constant <f64: 32.0> : tile<1xf64>
    %62 = divf %58, %61 rounding<nearest_even> : tile<1xf64>
    %63 = negf %62 : tile<1xf64>
    %64 = reshape %60 : tile<i32> -> tile<1xi32>
    %65 = broadcast %64 : tile<1xi32> -> tile<1xi32>
    %66 = iota : tile<1xi32>
    %67 = addi %65, %66 : tile<1xi32>
    %68 = reshape %arg4 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %69 = broadcast %68 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %70 = offset %69, %67 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %71 = store_ptr_tko weak %70, %63 token=%35 : tile<1xptr<f64>>, tile<1xf64> -> token
    return
  }
}
