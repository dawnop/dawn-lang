cuda_tile.module @m {
  entry @cce_row(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 32> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<32xi32>
    %8 = iota : tile<32xi32>
    %9 = addi %7, %8 : tile<32xi32>
    %10 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %11 = broadcast %10 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %12 = offset %11, %9 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<32xptr<f64>> -> tile<32xf64>, token
    %15 = reduce %13 dim=0 identities=[-Infinity : f64] : tile<32xf64> -> tile<f64> (%16: tile<f64>, %17: tile<f64>) {
      %18 = maxf %16, %17 : tile<f64>
      yield %18 : tile<f64>
    }
    %19 = reshape %15 : tile<f64> -> tile<1xf64>
    %20 = broadcast %19 : tile<1xf64> -> tile<32xf64>
    %21 = subf %13, %20 rounding<nearest_even> : tile<32xf64>
    %22 = exp %21 : tile<32xf64>
    %23 = reduce %22 dim=0 identities=[0.0 : f64] : tile<32xf64> -> tile<f64> (%24: tile<f64>, %25: tile<f64>) {
      %26 = addf %24, %25 rounding<nearest_even> : tile<f64>
      yield %26 : tile<f64>
    }
    %27 = constant <i32: 1> : tile<i32>
    %28 = muli %1, %27 : tile<i32>
    %29 = reshape %28 : tile<i32> -> tile<1xi32>
    %30 = broadcast %29 : tile<1xi32> -> tile<1xi32>
    %31 = iota : tile<1xi32>
    %32 = addi %30, %31 : tile<1xi32>
    %33 = reshape %arg1 : tile<ptr<i32>> -> tile<1xptr<i32>>
    %34 = broadcast %33 : tile<1xptr<i32>> -> tile<1xptr<i32>>
    %35 = offset %34, %32 : tile<1xptr<i32>>, tile<1xi32> -> tile<1xptr<i32>>
    %36, %37 = load_ptr_tko weak %35 token=%14 : tile<1xptr<i32>> -> tile<1xi32>, token
    %38 = constant <i32: 32> : tile<1xi32>
    %39 = muli %32, %38 : tile<1xi32>
    %40 = addi %39, %36 : tile<1xi32>
    %41 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %42 = broadcast %41 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %43 = offset %42, %40 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %44, %45 = load_ptr_tko weak %43 token=%37 : tile<1xptr<f64>> -> tile<1xf64>, token
    %46 = reshape %15 : tile<f64> -> tile<1xf64>
    %47 = broadcast %46 : tile<1xf64> -> tile<1xf64>
    %48 = reshape %23 : tile<f64> -> tile<1xf64>
    %49 = broadcast %48 : tile<1xf64> -> tile<1xf64>
    %50 = log %49 : tile<1xf64>
    %51 = addf %47, %50 rounding<nearest_even> : tile<1xf64>
    %52 = subf %51, %44 rounding<nearest_even> : tile<1xf64>
    %53 = constant <i32: 1> : tile<i32>
    %54 = muli %1, %53 : tile<i32>
    %55 = reshape %54 : tile<i32> -> tile<1xi32>
    %56 = broadcast %55 : tile<1xi32> -> tile<1xi32>
    %57 = iota : tile<1xi32>
    %58 = addi %56, %57 : tile<1xi32>
    %59 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %60 = broadcast %59 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %61 = offset %60, %58 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %62 = store_ptr_tko weak %61, %52 token=%45 : tile<1xptr<f64>>, tile<1xf64> -> token
    return
  }
}
