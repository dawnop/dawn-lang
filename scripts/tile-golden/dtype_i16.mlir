cuda_tile.module @m {
  entry @dtype_i16(%arg0: tile<ptr<i16>>, %arg1: tile<ptr<i16>>, %arg2: tile<ptr<i16>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 128> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<128xi32>
    %8 = iota : tile<128xi32>
    %9 = addi %7, %8 : tile<128xi32>
    %10 = reshape %arg0 : tile<ptr<i16>> -> tile<1xptr<i16>>
    %11 = broadcast %10 : tile<1xptr<i16>> -> tile<128xptr<i16>>
    %12 = offset %11, %9 : tile<128xptr<i16>>, tile<128xi32> -> tile<128xptr<i16>>
    %13, %14 = load_ptr_tko weak %12 token=%0 : tile<128xptr<i16>> -> tile<128xi16>, token
    %15 = reshape %arg1 : tile<ptr<i16>> -> tile<1xptr<i16>>
    %16 = broadcast %15 : tile<1xptr<i16>> -> tile<128xptr<i16>>
    %17 = offset %16, %9 : tile<128xptr<i16>>, tile<128xi32> -> tile<128xptr<i16>>
    %18, %19 = load_ptr_tko weak %17 token=%14 : tile<128xptr<i16>> -> tile<128xi16>, token
    %20 = constant <i32: 0> : tile<i32>
    %21 = addi %5, %20 : tile<i32>
    %22 = addi %13, %18 : tile<128xi16>
    %23 = reshape %21 : tile<i32> -> tile<1xi32>
    %24 = broadcast %23 : tile<1xi32> -> tile<128xi32>
    %25 = iota : tile<128xi32>
    %26 = addi %24, %25 : tile<128xi32>
    %27 = reshape %arg2 : tile<ptr<i16>> -> tile<1xptr<i16>>
    %28 = broadcast %27 : tile<1xptr<i16>> -> tile<128xptr<i16>>
    %29 = offset %28, %26 : tile<128xptr<i16>>, tile<128xi32> -> tile<128xptr<i16>>
    %30 = store_ptr_tko weak %29, %22 token=%19 : tile<128xptr<i16>>, tile<128xi16> -> token
    %31 = constant <i32: 512> : tile<i32>
    %32 = addi %5, %31 : tile<i32>
    %33 = subi %13, %18 : tile<128xi16>
    %34 = reshape %32 : tile<i32> -> tile<1xi32>
    %35 = broadcast %34 : tile<1xi32> -> tile<128xi32>
    %36 = iota : tile<128xi32>
    %37 = addi %35, %36 : tile<128xi32>
    %38 = reshape %arg2 : tile<ptr<i16>> -> tile<1xptr<i16>>
    %39 = broadcast %38 : tile<1xptr<i16>> -> tile<128xptr<i16>>
    %40 = offset %39, %37 : tile<128xptr<i16>>, tile<128xi32> -> tile<128xptr<i16>>
    %41 = store_ptr_tko weak %40, %33 token=%30 : tile<128xptr<i16>>, tile<128xi16> -> token
    %42 = constant <i32: 1024> : tile<i32>
    %43 = addi %5, %42 : tile<i32>
    %44 = muli %13, %18 : tile<128xi16>
    %45 = reshape %43 : tile<i32> -> tile<1xi32>
    %46 = broadcast %45 : tile<1xi32> -> tile<128xi32>
    %47 = iota : tile<128xi32>
    %48 = addi %46, %47 : tile<128xi32>
    %49 = reshape %arg2 : tile<ptr<i16>> -> tile<1xptr<i16>>
    %50 = broadcast %49 : tile<1xptr<i16>> -> tile<128xptr<i16>>
    %51 = offset %50, %48 : tile<128xptr<i16>>, tile<128xi32> -> tile<128xptr<i16>>
    %52 = store_ptr_tko weak %51, %44 token=%41 : tile<128xptr<i16>>, tile<128xi16> -> token
    %53 = constant <i32: 1536> : tile<i32>
    %54 = addi %5, %53 : tile<i32>
    %55 = constant <i16: 3> : tile<128xi16>
    %56 = shli %13, %55 : tile<128xi16>
    %57 = constant <i16: 2> : tile<128xi16>
    %58 = shri %56, %57 signed : tile<128xi16>
    %59 = reshape %54 : tile<i32> -> tile<1xi32>
    %60 = broadcast %59 : tile<1xi32> -> tile<128xi32>
    %61 = iota : tile<128xi32>
    %62 = addi %60, %61 : tile<128xi32>
    %63 = reshape %arg2 : tile<ptr<i16>> -> tile<1xptr<i16>>
    %64 = broadcast %63 : tile<1xptr<i16>> -> tile<128xptr<i16>>
    %65 = offset %64, %62 : tile<128xptr<i16>>, tile<128xi32> -> tile<128xptr<i16>>
    %66 = store_ptr_tko weak %65, %58 token=%52 : tile<128xptr<i16>>, tile<128xi16> -> token
    %67 = constant <i32: 2048> : tile<i32>
    %68 = addi %5, %67 : tile<i32>
    %69 = itof %13 signed rounding<nearest_even> : tile<128xi16> -> tile<128xf64>
    %70 = ftoi %69 signed rounding<nearest_int_to_zero> : tile<128xf64> -> tile<128xi16>
    %71 = reshape %68 : tile<i32> -> tile<1xi32>
    %72 = broadcast %71 : tile<1xi32> -> tile<128xi32>
    %73 = iota : tile<128xi32>
    %74 = addi %72, %73 : tile<128xi32>
    %75 = reshape %arg2 : tile<ptr<i16>> -> tile<1xptr<i16>>
    %76 = broadcast %75 : tile<1xptr<i16>> -> tile<128xptr<i16>>
    %77 = offset %76, %74 : tile<128xptr<i16>>, tile<128xi32> -> tile<128xptr<i16>>
    %78 = store_ptr_tko weak %77, %70 token=%66 : tile<128xptr<i16>>, tile<128xi16> -> token
    return
  }
}
