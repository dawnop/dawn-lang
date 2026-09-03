cuda_tile.module @m {
  entry @gae(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 64> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<64xi32>
    %8 = iota : tile<64xi32>
    %9 = addi %7, %8 : tile<64xi32>
    %10 = constant <i32: 1> : tile<64xi32>
    %11 = addi %9, %10 : tile<64xi32>
    %12 = constant <i32: 255> : tile<64xi32>
    %13 = andi %11, %12 : tile<64xi32>
    %14 = constant <i32: 0> : tile<i32>
    %15 = reshape %14 : tile<i32> -> tile<1xi32>
    %16 = broadcast %15 : tile<1xi32> -> tile<64xi32>
    %17 = iota : tile<64xi32>
    %18 = addi %16, %17 : tile<64xi32>
    %19 = constant <i32: 0> : tile<64xi32>
    %20 = cmpi greater_than_or_equal %18, %19, signed : tile<64xi32> -> tile<64xi1>
    %21 = constant <i32: 63> : tile<64xi32>
    %22 = cmpi less_than %18, %21, signed : tile<64xi32> -> tile<64xi1>
    %23 = constant <i1: 0> : tile<64xi1>
    %24 = select %20, %22, %23 : tile<64xi1>, tile<64xi1>
    %25 = constant <f64: 0.0> : tile<64xf64>
    %26 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %27 = broadcast %26 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %28 = offset %27, %13 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %29, %30 = load_ptr_tko weak %28, %24, %25 token=%0 : tile<64xptr<f64>>, tile<64xi1>, tile<64xf64> -> tile<64xf64>, token
    %31 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %32 = broadcast %31 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %33 = offset %32, %9 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %34, %35 = load_ptr_tko weak %33 token=%30 : tile<64xptr<f64>> -> tile<64xf64>, token
    %36 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %37 = broadcast %36 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %38 = offset %37, %9 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %39, %40 = load_ptr_tko weak %38 token=%35 : tile<64xptr<f64>> -> tile<64xf64>, token
    %41 = constant <f64: 0.99> : tile<64xf64>
    %42 = mulf %41, %29 rounding<nearest_even> : tile<64xf64>
    %43 = addf %39, %42 rounding<nearest_even> : tile<64xf64>
    %44 = subf %43, %34 rounding<nearest_even> : tile<64xf64>
    %45 = constant <f64: 0.9405> : tile<64xf64>
    %46, %47 = scan %45, %44 dim=0 reverse=true identities=[1.0 : f64, 0.0 : f64] : tile<64xf64>, tile<64xf64> -> tile<64xf64>, tile<64xf64> (%48: tile<f64>, %49: tile<f64>, %50: tile<f64>, %51: tile<f64>) {
      %52 = mulf %49, %48 rounding<nearest_even> : tile<f64>
      %53 = fma %49, %50, %51 rounding<nearest_even> : tile<f64>
      yield %52, %53 : tile<f64>, tile<f64>
    }
    %54 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %55 = broadcast %54 : tile<1xptr<f64>> -> tile<64xptr<f64>>
    %56 = offset %55, %9 : tile<64xptr<f64>>, tile<64xi32> -> tile<64xptr<f64>>
    %57 = store_ptr_tko weak %56, %47 token=%40 : tile<64xptr<f64>>, tile<64xf64> -> token
    return
  }
}
