cuda_tile.module @m {
  entry @monte_carlo(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 1024> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<1024xi32>
    %8 = iota : tile<1024xi32>
    %9 = addi %7, %8 : tile<1024xi32>
    %10 = constant <i32: 1000> : tile<1024xi32>
    %11 = cmpi less_than %9, %10, signed : tile<1024xi32> -> tile<1024xi1>
    %12 = constant <f64: 0.0> : tile<1024xf64>
    %13 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %14 = broadcast %13 : tile<1xptr<f64>> -> tile<1024xptr<f64>>
    %15 = offset %14, %9 : tile<1024xptr<f64>>, tile<1024xi32> -> tile<1024xptr<f64>>
    %16, %17 = load_ptr_tko weak %15, %11, %12 token=%0 : tile<1024xptr<f64>>, tile<1024xi1>, tile<1024xf64> -> tile<1024xf64>, token
    %18 = reduce %16 dim=0 identities=[0.0 : f64] : tile<1024xf64> -> tile<f64> (%19: tile<f64>, %20: tile<f64>) {
      %21 = addf %19, %20 rounding<nearest_even> : tile<f64>
      yield %21 : tile<f64>
    }
    %22 = reshape %18 : tile<f64> -> tile<1xf64>
    %23 = broadcast %22 : tile<1xf64> -> tile<1xf64>
    %24 = constant <f64: 0.002> : tile<1xf64>
    %25 = mulf %23, %24 rounding<nearest_even> : tile<1xf64>
    %26 = constant <i32: 1> : tile<i32>
    %27 = muli %1, %26 : tile<i32>
    %28 = reshape %27 : tile<i32> -> tile<1xi32>
    %29 = broadcast %28 : tile<1xi32> -> tile<1xi32>
    %30 = iota : tile<1xi32>
    %31 = addi %29, %30 : tile<1xi32>
    %32 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %33 = broadcast %32 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %34 = offset %33, %31 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %35 = store_ptr_tko weak %34, %25 token=%17 : tile<1xptr<f64>>, tile<1xf64> -> token
    return
  }
}
