cuda_tile.module @m {
  entry @dot(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
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
    %18 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %19 = broadcast %18 : tile<1xptr<f64>> -> tile<1024xptr<f64>>
    %20 = offset %19, %9 : tile<1024xptr<f64>>, tile<1024xi32> -> tile<1024xptr<f64>>
    %21, %22 = load_ptr_tko weak %20, %11, %12 token=%17 : tile<1024xptr<f64>>, tile<1024xi1>, tile<1024xf64> -> tile<1024xf64>, token
    %23 = mulf %16, %21 rounding<nearest_even> : tile<1024xf64>
    %24 = reduce %23 dim=0 identities=[0.0 : f64] : tile<1024xf64> -> tile<f64> (%25: tile<f64>, %26: tile<f64>) {
      %27 = addf %25, %26 rounding<nearest_even> : tile<f64>
      yield %27 : tile<f64>
    }
    %28 = reshape %24 : tile<f64> -> tile<1xf64>
    %29 = broadcast %28 : tile<1xf64> -> tile<1xf64>
    %30 = constant <i32: 1> : tile<i32>
    %31 = muli %1, %30 : tile<i32>
    %32 = reshape %31 : tile<i32> -> tile<1xi32>
    %33 = broadcast %32 : tile<1xi32> -> tile<1xi32>
    %34 = iota : tile<1xi32>
    %35 = addi %33, %34 : tile<1xi32>
    %36 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %37 = broadcast %36 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %38 = offset %37, %35 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %39 = store_ptr_tko weak %38, %29 token=%22 : tile<1xptr<f64>>, tile<1xf64> -> token
    return
  }
}
