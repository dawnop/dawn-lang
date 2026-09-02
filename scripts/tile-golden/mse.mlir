cuda_tile.module @m {
  entry @mse(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
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
    %23 = subf %16, %21 rounding<nearest_even> : tile<1024xf64>
    %24 = mulf %23, %23 rounding<nearest_even> : tile<1024xf64>
    %25 = reduce %24 dim=0 identities=[0.0 : f64] : tile<1024xf64> -> tile<f64> (%26: tile<f64>, %27: tile<f64>) {
      %28 = addf %26, %27 rounding<nearest_even> : tile<f64>
      yield %28 : tile<f64>
    }
    %29 = reshape %25 : tile<f64> -> tile<1xf64>
    %30 = broadcast %29 : tile<1xf64> -> tile<1xf64>
    %31 = constant <f64: 1000.0> : tile<1xf64>
    %32 = divf %30, %31 rounding<nearest_even> : tile<1xf64>
    %33 = constant <i32: 1> : tile<i32>
    %34 = muli %1, %33 : tile<i32>
    %35 = reshape %34 : tile<i32> -> tile<1xi32>
    %36 = broadcast %35 : tile<1xi32> -> tile<1xi32>
    %37 = iota : tile<1xi32>
    %38 = addi %36, %37 : tile<1xi32>
    %39 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %40 = broadcast %39 : tile<1xptr<f64>> -> tile<1xptr<f64>>
    %41 = offset %40, %38 : tile<1xptr<f64>>, tile<1xi32> -> tile<1xptr<f64>>
    %42 = store_ptr_tko weak %41, %32 token=%22 : tile<1xptr<f64>>, tile<1xf64> -> token
    return
  }
}
