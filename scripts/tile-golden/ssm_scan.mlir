cuda_tile.module @m {
  entry @ssm_scan(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>, %arg4: tile<ptr<f64>>, %arg5: tile<ptr<f64>>, %arg6: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7 = constant <i32: 256> : tile<i32>
    %8 = muli %1, %7 : tile<i32>
    %9 = addi %8, %5 : tile<i32>
    %10 = constant <i32: 512> : tile<i32>
    %11 = muli %1, %10 : tile<i32>
    %12 = constant <i32: 16> : tile<i32>
    %13 = muli %5, %12 : tile<i32>
    %14 = reshape %9 : tile<i32> -> tile<1x1xi32>
    %15 = broadcast %14 : tile<1x1xi32> -> tile<32x16xi32>
    %16 = iota : tile<32xi32>
    %17 = reshape %16 : tile<32xi32> -> tile<32x1xi32>
    %18 = broadcast %17 : tile<32x1xi32> -> tile<32x16xi32>
    %19 = constant <i32: 8> : tile<32x16xi32>
    %20 = muli %18, %19 : tile<32x16xi32>
    %21 = addi %15, %20 : tile<32x16xi32>
    %22 = iota : tile<16xi32>
    %23 = reshape %22 : tile<16xi32> -> tile<1x16xi32>
    %24 = broadcast %23 : tile<1x16xi32> -> tile<32x16xi32>
    %25 = constant <i32: 0> : tile<32x16xi32>
    %26 = muli %24, %25 : tile<32x16xi32>
    %27 = addi %21, %26 : tile<32x16xi32>
    %28 = reshape %arg1 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %29 = broadcast %28 : tile<1x1xptr<f64>> -> tile<32x16xptr<f64>>
    %30 = offset %29, %27 : tile<32x16xptr<f64>>, tile<32x16xi32> -> tile<32x16xptr<f64>>
    %31, %32 = load_ptr_tko weak %30 token=%0 : tile<32x16xptr<f64>> -> tile<32x16xf64>, token
    %33 = reshape %arg0 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %34 = broadcast %33 : tile<1x1xptr<f64>> -> tile<32x16xptr<f64>>
    %35 = offset %34, %27 : tile<32x16xptr<f64>>, tile<32x16xi32> -> tile<32x16xptr<f64>>
    %36, %37 = load_ptr_tko weak %35 token=%32 : tile<32x16xptr<f64>> -> tile<32x16xf64>, token
    %38 = reshape %13 : tile<i32> -> tile<1x1xi32>
    %39 = broadcast %38 : tile<1x1xi32> -> tile<32x16xi32>
    %40 = iota : tile<32xi32>
    %41 = reshape %40 : tile<32xi32> -> tile<32x1xi32>
    %42 = broadcast %41 : tile<32x1xi32> -> tile<32x16xi32>
    %43 = constant <i32: 0> : tile<32x16xi32>
    %44 = muli %42, %43 : tile<32x16xi32>
    %45 = addi %39, %44 : tile<32x16xi32>
    %46 = iota : tile<16xi32>
    %47 = reshape %46 : tile<16xi32> -> tile<1x16xi32>
    %48 = broadcast %47 : tile<1x16xi32> -> tile<32x16xi32>
    %49 = addi %45, %48 : tile<32x16xi32>
    %50 = reshape %arg2 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %51 = broadcast %50 : tile<1x1xptr<f64>> -> tile<32x16xptr<f64>>
    %52 = offset %51, %49 : tile<32x16xptr<f64>>, tile<32x16xi32> -> tile<32x16xptr<f64>>
    %53, %54 = load_ptr_tko weak %52 token=%37 : tile<32x16xptr<f64>> -> tile<32x16xf64>, token
    %55 = mulf %31, %53 rounding<nearest_even> : tile<32x16xf64>
    %56 = exp %55 : tile<32x16xf64>
    %57 = reshape %11 : tile<i32> -> tile<1x1xi32>
    %58 = broadcast %57 : tile<1x1xi32> -> tile<32x16xi32>
    %59 = iota : tile<32xi32>
    %60 = reshape %59 : tile<32xi32> -> tile<32x1xi32>
    %61 = broadcast %60 : tile<32x1xi32> -> tile<32x16xi32>
    %62 = constant <i32: 16> : tile<32x16xi32>
    %63 = muli %61, %62 : tile<32x16xi32>
    %64 = addi %58, %63 : tile<32x16xi32>
    %65 = iota : tile<16xi32>
    %66 = reshape %65 : tile<16xi32> -> tile<1x16xi32>
    %67 = broadcast %66 : tile<1x16xi32> -> tile<32x16xi32>
    %68 = addi %64, %67 : tile<32x16xi32>
    %69 = reshape %arg3 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %70 = broadcast %69 : tile<1x1xptr<f64>> -> tile<32x16xptr<f64>>
    %71 = offset %70, %68 : tile<32x16xptr<f64>>, tile<32x16xi32> -> tile<32x16xptr<f64>>
    %72, %73 = load_ptr_tko weak %71 token=%54 : tile<32x16xptr<f64>> -> tile<32x16xf64>, token
    %74 = mulf %31, %72 rounding<nearest_even> : tile<32x16xf64>
    %75 = mulf %74, %36 rounding<nearest_even> : tile<32x16xf64>
    %76, %77 = scan %56, %75 dim=0 reverse=false identities=[1.0 : f64, 0.0 : f64] : tile<32x16xf64>, tile<32x16xf64> -> tile<32x16xf64>, tile<32x16xf64> (%78: tile<f64>, %79: tile<f64>, %80: tile<f64>, %81: tile<f64>) {
      %82 = mulf %79, %78 rounding<nearest_even> : tile<f64>
      %83 = fma %79, %80, %81 rounding<nearest_even> : tile<f64>
      yield %82, %83 : tile<f64>, tile<f64>
    }
    %84 = reshape %arg4 : tile<ptr<f64>> -> tile<1x1xptr<f64>>
    %85 = broadcast %84 : tile<1x1xptr<f64>> -> tile<32x16xptr<f64>>
    %86 = offset %85, %68 : tile<32x16xptr<f64>>, tile<32x16xi32> -> tile<32x16xptr<f64>>
    %87, %88 = load_ptr_tko weak %86 token=%73 : tile<32x16xptr<f64>> -> tile<32x16xf64>, token
    %89 = mulf %87, %77 rounding<nearest_even> : tile<32x16xf64>
    %90 = reduce %89 dim=1 identities=[0.0 : f64] : tile<32x16xf64> -> tile<32xf64> (%91: tile<f64>, %92: tile<f64>) {
      %93 = addf %91, %92 rounding<nearest_even> : tile<f64>
      yield %93 : tile<f64>
    }
    %94 = reshape %5 : tile<i32> -> tile<1xi32>
    %95 = broadcast %94 : tile<1xi32> -> tile<32xi32>
    %96 = iota : tile<32xi32>
    %97 = constant <i32: 0> : tile<32xi32>
    %98 = muli %96, %97 : tile<32xi32>
    %99 = addi %95, %98 : tile<32xi32>
    %100 = reshape %arg5 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %101 = broadcast %100 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %102 = offset %101, %99 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %103, %104 = load_ptr_tko weak %102 token=%88 : tile<32xptr<f64>> -> tile<32xf64>, token
    %105 = reshape %9 : tile<i32> -> tile<1xi32>
    %106 = broadcast %105 : tile<1xi32> -> tile<32xi32>
    %107 = iota : tile<32xi32>
    %108 = constant <i32: 8> : tile<32xi32>
    %109 = muli %107, %108 : tile<32xi32>
    %110 = addi %106, %109 : tile<32xi32>
    %111 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %112 = broadcast %111 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %113 = offset %112, %110 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %114, %115 = load_ptr_tko weak %113 token=%104 : tile<32xptr<f64>> -> tile<32xf64>, token
    %116 = mulf %103, %114 rounding<nearest_even> : tile<32xf64>
    %117 = addf %90, %116 rounding<nearest_even> : tile<32xf64>
    %118 = reshape %arg6 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %119 = broadcast %118 : tile<1xptr<f64>> -> tile<32xptr<f64>>
    %120 = offset %119, %110 : tile<32xptr<f64>>, tile<32xi32> -> tile<32xptr<f64>>
    %121 = store_ptr_tko weak %120, %117 token=%115 : tile<32xptr<f64>>, tile<32xf64> -> token
    return
  }
}
