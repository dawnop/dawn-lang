cuda_tile.module @m {
  entry @gpt_fc(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 0> : tile<i32>
    %5 = constant <i32: 2> : tile<i32>
    %6 = constant <i32: 1> : tile<i32>
    %7 = constant <f64: 0.0> : tile<64x32xf64>
    %8, %9 = for %10 in (%4 to %5, step %6) : tile<i32> iter_values(%11 = %7, %12 = %0) -> (tile<64x32xf64>, token) {
      %13 = constant <i32: 32> : tile<i32>
      %14 = muli %10, %13 : tile<i32>
      %15 = reshape %14 : tile<i32> -> tile<1x1xi32>
      %16 = broadcast %15 : tile<1x1xi32> -> tile<64x32xi32>
      %17 = iota : tile<64xi32>
      %18 = reshape %17 : tile<64xi32> -> tile<64x1xi32>
      %19 = broadcast %18 : tile<64x1xi32> -> tile<64x32xi32>
      %20 = constant <i32: 64> : tile<64x32xi32>
      %21 = muli %19, %20 : tile<64x32xi32>
      %22 = addi %16, %21 : tile<64x32xi32>
      %23 = iota : tile<32xi32>
      %24 = reshape %23 : tile<32xi32> -> tile<1x32xi32>
      %25 = broadcast %24 : tile<1x32xi32> -> tile<64x32xi32>
      %26 = addi %22, %25 : tile<64x32xi32>
      %27 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %28 = broadcast %27 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
      %29 = offset %28, %26 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
      %30, %31 = load_ptr_tko weak %29 token=%12 : tile<64x32xptr<f64>> -> tile<64x32xf64>, token
      %32 = constant <i32: 4096> : tile<i32>
      %33 = muli %10, %32 : tile<i32>
      %34 = constant <i32: 32> : tile<i32>
      %35 = muli %2, %34 : tile<i32>
      %36 = addi %33, %35 : tile<i32>
      %37 = reshape %36 : tile<i32> -> tile<1x1xi32>
      %38 = broadcast %37 : tile<1x1xi32> -> tile<32x32xi32>
      %39 = iota : tile<32xi32>
      %40 = reshape %39 : tile<32xi32> -> tile<32x1xi32>
      %41 = broadcast %40 : tile<32x1xi32> -> tile<32x32xi32>
      %42 = constant <i32: 128> : tile<32x32xi32>
      %43 = muli %41, %42 : tile<32x32xi32>
      %44 = addi %38, %43 : tile<32x32xi32>
      %45 = iota : tile<32xi32>
      %46 = reshape %45 : tile<32xi32> -> tile<1x32xi32>
      %47 = broadcast %46 : tile<1x32xi32> -> tile<32x32xi32>
      %48 = addi %44, %47 : tile<32x32xi32>
      %49 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
      %50 = broadcast %49 : tile<1x1xptr<f64>> -> tile<32x32xptr<f64>>
      %51 = offset %50, %48 : tile<32x32xptr<f64>>, tile<32x32xi32> -> tile<32x32xptr<f64>>
      %52, %53 = load_ptr_tko weak %51 token=%31 : tile<32x32xptr<f64>> -> tile<32x32xf64>, token
      %54 = mmaf %30, %52, %11 : tile<64x32xf64>, tile<32x32xf64>, tile<64x32xf64>
      continue %54, %53 : tile<64x32xf64>, token
    }
    %55 = constant <i32: 32> : tile<i32>
    %56 = muli %2, %55 : tile<i32>
    %57 = reshape %56 : tile<i32> -> tile<1x1xi32>
    %58 = broadcast %57 : tile<1x1xi32> -> tile<64x32xi32>
    %59 = iota : tile<64xi32>
    %60 = reshape %59 : tile<64xi32> -> tile<64x1xi32>
    %61 = broadcast %60 : tile<64x1xi32> -> tile<64x32xi32>
    %62 = constant <i32: 0> : tile<64x32xi32>
    %63 = muli %61, %62 : tile<64x32xi32>
    %64 = addi %58, %63 : tile<64x32xi32>
    %65 = iota : tile<32xi32>
    %66 = reshape %65 : tile<32xi32> -> tile<1x32xi32>
    %67 = broadcast %66 : tile<1x32xi32> -> tile<64x32xi32>
    %68 = addi %64, %67 : tile<64x32xi32>
    %69 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %70 = broadcast %69 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
    %71 = offset %70, %68 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
    %72, %73 = load_ptr_tko weak %71 token=%9 : tile<64x32xptr<f64>> -> tile<64x32xf64>, token
    %74 = constant <i32: 32> : tile<i32>
    %75 = muli %2, %74 : tile<i32>
    %76 = addf %8, %72 rounding<nearest_even> : tile<64x32xf64>
    %77 = reshape %75 : tile<i32> -> tile<1x1xi32>
    %78 = broadcast %77 : tile<1x1xi32> -> tile<64x32xi32>
    %79 = iota : tile<64xi32>
    %80 = reshape %79 : tile<64xi32> -> tile<64x1xi32>
    %81 = broadcast %80 : tile<64x1xi32> -> tile<64x32xi32>
    %82 = constant <i32: 128> : tile<64x32xi32>
    %83 = muli %81, %82 : tile<64x32xi32>
    %84 = addi %78, %83 : tile<64x32xi32>
    %85 = iota : tile<32xi32>
    %86 = reshape %85 : tile<32xi32> -> tile<1x32xi32>
    %87 = broadcast %86 : tile<1x32xi32> -> tile<64x32xi32>
    %88 = addi %84, %87 : tile<64x32xi32>
    %89 = reshape %arg3 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %90 = broadcast %89 : tile<1x1xptr<f64>> -> tile<64x32xptr<f64>>
    %91 = offset %90, %88 : tile<64x32xptr<f64>>, tile<64x32xi32> -> tile<64x32xptr<f64>>
    %92 = store_ptr_tko weak %91, %76 token=%73 : tile<64x32xptr<f64>>, tile<64x32xf64> -> token
    return
  }
}
