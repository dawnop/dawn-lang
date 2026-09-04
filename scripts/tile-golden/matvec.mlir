cuda_tile.module @m {
  entry @matvec(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = reshape %1 : tile<i32> -> tile<1x1xi32>
    %3 = broadcast %2 : tile<1x1xi32> -> tile<64x64xi32>
    %4 = iota : tile<64xi32>
    %5 = reshape %4 : tile<64xi32> -> tile<64x1xi32>
    %6 = broadcast %5 : tile<64x1xi32> -> tile<64x64xi32>
    %7 = constant <i32: 64> : tile<64x64xi32>
    %8 = muli %6, %7 : tile<64x64xi32>
    %9 = addi %3, %8 : tile<64x64xi32>
    %10 = iota : tile<64xi32>
    %11 = reshape %10 : tile<64xi32> -> tile<1x64xi32>
    %12 = broadcast %11 : tile<1x64xi32> -> tile<64x64xi32>
    %13 = addi %9, %12 : tile<64x64xi32>
    %14 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %15 = broadcast %14 : tile<1x1xptr<f64>> -> tile<64x64xptr<f64>>
    %16 = offset %15, %13 : tile<64x64xptr<f64>>, tile<64x64xi32> -> tile<64x64xptr<f64>>
    %17, %18 = load_ptr_tko weak %16 token=%0 : tile<64x64xptr<f64>> -> tile<64x64xf64>, token
    %19 = constant <i32: 0> : tile<i32>
    %20 = reshape %19 : tile<i32> -> tile<1x1xi32>
    %21 = broadcast %20 : tile<1x1xi32> -> tile<64x64xi32>
    %22 = iota : tile<64xi32>
    %23 = reshape %22 : tile<64xi32> -> tile<64x1xi32>
    %24 = broadcast %23 : tile<64x1xi32> -> tile<64x64xi32>
    %25 = constant <i32: 0> : tile<64x64xi32>
    %26 = muli %24, %25 : tile<64x64xi32>
    %27 = addi %21, %26 : tile<64x64xi32>
    %28 = iota : tile<64xi32>
    %29 = reshape %28 : tile<64xi32> -> tile<1x64xi32>
    %30 = broadcast %29 : tile<1x64xi32> -> tile<64x64xi32>
    %31 = addi %27, %30 : tile<64x64xi32>
    %32 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %33 = broadcast %32 : tile<1x1xptr<f64>> -> tile<64x64xptr<f64>>
    %34 = offset %33, %31 : tile<64x64xptr<f64>>, tile<64x64xi32> -> tile<64x64xptr<f64>>
    %35, %36 = load_ptr_tko weak %34 token=%18 : tile<64x64xptr<f64>> -> tile<64x64xf64>, token
    %37 = mulf %17, %35 rounding<nearest_even> : tile<64x64xf64>
    %38 = reduce %37 dim=1 identities=[0.0 : f64] : tile<64x64xf64> -> tile<64xf64> (%39: tile<f64>, %40: tile<f64>) {
      %41 = addf %39, %40 rounding<nearest_even> : tile<f64>
      yield %41 : tile<f64>
    }
    %42 = constant <i32: 0> : tile<i32>
    %43 = reshape %42 : tile<i32> -> tile<1xi32>
    %44 = broadcast %43 : tile<1xi32> -> tile<64xi32>
    %45 = iota : tile<64xi32>
    %46 = addi %44, %45 : tile<64xi32>
    %47 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %48 = broadcast %47 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %49 = offset %48, %46 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %50 = store_ptr_tko weak %49, %38 token=%36 : tile<64xptr<f64>>, tile<64xf64> -> token
    return
  }
}
