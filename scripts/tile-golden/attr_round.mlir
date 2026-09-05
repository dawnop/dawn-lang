cuda_tile.module @m {
  entry @attr_round(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 768> : tile<i32>
    %7 = muli %1, %6 : tile<i32>
    %8 = reshape %5 : tile<i32> -> tile<1xi32>
    %9 = broadcast %8 : tile<1xi32> -> tile<128xi32>
    %10 = iota : tile<128xi32>
    %11 = addi %9, %10 : tile<128xi32>
    %12 = reshape %arg0 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %13 = broadcast %12 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %14 = offset %13, %11 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %15, %16 = load_ptr_tko weak %14 token=%0 : tile<128xptr<f64>> -> tile<128xf64>, token
    %17 = ftof %15 rounding<nearest_even> : tile<128xf64> -> tile<128xf32>
    %18 = reshape %arg1 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %19 = broadcast %18 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %20 = offset %19, %11 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %21, %22 = load_ptr_tko weak %20 token=%16 : tile<128xptr<f64>> -> tile<128xf64>, token
    %23 = ftof %21 rounding<nearest_even> : tile<128xf64> -> tile<128xf32>
    %24 = addf %17, %23 rounding<negative_inf> : tile<128xf32>
    %25 = ftof %24 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %26 = reshape %7 : tile<i32> -> tile<1xi32>
    %27 = broadcast %26 : tile<1xi32> -> tile<128xi32>
    %28 = iota : tile<128xi32>
    %29 = addi %27, %28 : tile<128xi32>
    %30 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %31 = broadcast %30 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %32 = offset %31, %29 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %33 = store_ptr_tko weak %32, %25 token=%22 : tile<128xptr<f64>>, tile<128xf64> -> token
    %34 = constant <i32: 128> : tile<i32>
    %35 = addi %7, %34 : tile<i32>
    %36 = addf %17, %23 rounding<positive_inf> : tile<128xf32>
    %37 = ftof %36 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %38 = reshape %35 : tile<i32> -> tile<1xi32>
    %39 = broadcast %38 : tile<1xi32> -> tile<128xi32>
    %40 = iota : tile<128xi32>
    %41 = addi %39, %40 : tile<128xi32>
    %42 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %43 = broadcast %42 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %44 = offset %43, %41 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %45 = store_ptr_tko weak %44, %37 token=%33 : tile<128xptr<f64>>, tile<128xf64> -> token
    %46 = constant <i32: 256> : tile<i32>
    %47 = addi %7, %46 : tile<i32>
    %48 = mulf %17, %23 rounding<negative_inf> : tile<128xf32>
    %49 = ftof %48 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %50 = reshape %47 : tile<i32> -> tile<1xi32>
    %51 = broadcast %50 : tile<1xi32> -> tile<128xi32>
    %52 = iota : tile<128xi32>
    %53 = addi %51, %52 : tile<128xi32>
    %54 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %55 = broadcast %54 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %56 = offset %55, %53 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %57 = store_ptr_tko weak %56, %49 token=%45 : tile<128xptr<f64>>, tile<128xf64> -> token
    %58 = constant <i32: 384> : tile<i32>
    %59 = addi %7, %58 : tile<i32>
    %60 = mulf %17, %23 rounding<positive_inf> : tile<128xf32>
    %61 = ftof %60 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %62 = reshape %59 : tile<i32> -> tile<1xi32>
    %63 = broadcast %62 : tile<1xi32> -> tile<128xi32>
    %64 = iota : tile<128xi32>
    %65 = addi %63, %64 : tile<128xi32>
    %66 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %67 = broadcast %66 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %68 = offset %67, %65 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %69 = store_ptr_tko weak %68, %61 token=%57 : tile<128xptr<f64>>, tile<128xf64> -> token
    %70 = constant <i32: 512> : tile<i32>
    %71 = addi %7, %70 : tile<i32>
    %72 = divf %17, %23 rounding<negative_inf> : tile<128xf32>
    %73 = ftof %72 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %74 = reshape %71 : tile<i32> -> tile<1xi32>
    %75 = broadcast %74 : tile<1xi32> -> tile<128xi32>
    %76 = iota : tile<128xi32>
    %77 = addi %75, %76 : tile<128xi32>
    %78 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %79 = broadcast %78 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %80 = offset %79, %77 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %81 = store_ptr_tko weak %80, %73 token=%69 : tile<128xptr<f64>>, tile<128xf64> -> token
    %82 = constant <i32: 640> : tile<i32>
    %83 = addi %7, %82 : tile<i32>
    %84 = divf %17, %23 rounding<positive_inf> : tile<128xf32>
    %85 = ftof %84 rounding<nearest_even> : tile<128xf32> -> tile<128xf64>
    %86 = reshape %83 : tile<i32> -> tile<1xi32>
    %87 = broadcast %86 : tile<1xi32> -> tile<128xi32>
    %88 = iota : tile<128xi32>
    %89 = addi %87, %88 : tile<128xi32>
    %90 = reshape %arg2 : tile<ptr<f64>> -> tile<1xptr<f64>>
    %91 = broadcast %90 : tile<1xptr<f64>> -> tile<128xptr<f64>>
    %92 = offset %91, %89 : tile<128xptr<f64>>, tile<128xi32> -> tile<128xptr<f64>>
    %93 = store_ptr_tko weak %92, %85 token=%81 : tile<128xptr<f64>>, tile<128xf64> -> token
    return
  }
}
